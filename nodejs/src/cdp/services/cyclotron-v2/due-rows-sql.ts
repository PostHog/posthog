import { escapeLiteral } from 'pg'

import { CYCLOTRON_COUNTER_MAX } from './types'

const CLAIM_UPDATE = `UPDATE cyclotron_jobs
SET status = 'running',
    lock_id = $3,
    last_heartbeat = NOW(),
    last_transition = NOW(),
    transition_count = LEAST(transition_count + 1, ${CYCLOTRON_COUNTER_MAX})`

const CLAIM_RETURNING = `RETURNING
    cyclotron_jobs.id,
    cyclotron_jobs.team_id,
    cyclotron_jobs.function_id,
    cyclotron_jobs.queue_name,
    cyclotron_jobs.priority,
    cyclotron_jobs.scheduled,
    cyclotron_jobs.created,
    cyclotron_jobs.parent_run_id,
    cyclotron_jobs.transition_count,
    cyclotron_jobs.state,
    cyclotron_jobs.distinct_id,
    cyclotron_jobs.person_id,
    cyclotron_jobs.action_id,
    cyclotron_jobs.cancel_requested_at,
    cyclotron_jobs.lock_id`

const priorityClassesCte = (queueName: string): string => `priority_classes AS (
    (SELECT priority FROM cyclotron_jobs
     WHERE status = 'available' AND queue_name = ${queueName}
     ORDER BY priority DESC, scheduled DESC
     LIMIT 1)
    UNION ALL
    SELECT lower_class.priority
    FROM priority_classes c
    CROSS JOIN LATERAL (
        SELECT j.priority FROM cyclotron_jobs j
        WHERE j.status = 'available' AND j.queue_name = ${queueName} AND j.priority < c.priority
        ORDER BY j.priority DESC, j.scheduled DESC
        LIMIT 1
    ) lower_class
)`

const PRIORITY_CLASSES_CTE = priorityClassesCte('$1')

type RowFilter = (alias: string) => string

const anyRow: RowFilter = () => ''
// The fair dequeue hides the queue name from the planner, so the literal is what lets each due scan read the
// partial email index for its kind of send instead of reading every due send of the other kind and discarding it.
const emailRows =
    (queueName: string, fileBytes: 'IS NULL' | 'IS NOT NULL'): RowFilter =>
    (alias) =>
        `AND ${alias}queue_name = ${escapeLiteral(queueName)} AND ${alias}file_bytes ${fileBytes}`

const countWorkSql = (only: RowFilter): string => `WITH RECURSIVE ${PRIORITY_CLASSES_CTE}
SELECT COUNT(*)::int AS n FROM (
    SELECT 1 FROM priority_classes c
    CROSS JOIN LATERAL (
        SELECT 1 FROM cyclotron_jobs j
        WHERE j.status = 'available' AND j.queue_name = $1 AND j.priority = c.priority AND j.scheduled <= NOW() ${only('j.')}
        ORDER BY j.scheduled ASC
        LIMIT $2
    ) due
    LIMIT $2
) sub`

const dequeueJobsSql = (only: RowFilter): string => `WITH RECURSIVE ${PRIORITY_CLASSES_CTE},
available AS (
    SELECT due.id
    FROM (SELECT priority FROM priority_classes ORDER BY priority ASC) c
    CROSS JOIN LATERAL (
        SELECT j.id FROM cyclotron_jobs j
        WHERE j.status = 'available' AND j.queue_name = $1 AND j.priority = c.priority AND j.scheduled <= NOW() ${only('j.')}
        ORDER BY j.scheduled ASC
        LIMIT $2
        FOR UPDATE SKIP LOCKED
    ) due
    LIMIT $2
)
${CLAIM_UPDATE}
WHERE cyclotron_jobs.id = ANY(ARRAY(SELECT id FROM available))
${CLAIM_RETURNING}`

const QUEUE_CLASSES_CTE = `queue_classes AS (
    (SELECT queue_name, priority FROM cyclotron_jobs
     WHERE status = 'available'
     ORDER BY queue_name DESC, priority DESC, scheduled DESC
     LIMIT 1)
    UNION ALL
    SELECT lower_class.queue_name, lower_class.priority
    FROM queue_classes c
    CROSS JOIN LATERAL (
        SELECT j.queue_name, j.priority FROM cyclotron_jobs j
        WHERE j.status = 'available' AND (j.queue_name, j.priority) < (c.queue_name, c.priority)
        ORDER BY j.queue_name DESC, j.priority DESC, j.scheduled DESC
        LIMIT 1
    ) lower_class
)`

export const QUEUE_DEPTH_SQL = `WITH RECURSIVE ${QUEUE_CLASSES_CTE}
SELECT COALESCE(SUM(due.count), 0) AS count
FROM queue_classes c
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS count FROM cyclotron_jobs j
    WHERE j.status = 'available' AND j.queue_name = c.queue_name AND j.priority = c.priority AND j.scheduled <= NOW()
) due`

export const cappedQueueDepthSql = (limit: number): string => `WITH RECURSIVE ${QUEUE_CLASSES_CTE}
SELECT COALESCE(SUM(due.count), 0) AS count
FROM queue_classes c
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS count FROM (
        SELECT 1 FROM cyclotron_jobs j
        WHERE j.status = 'available' AND j.queue_name = c.queue_name AND j.priority = c.priority AND j.scheduled <= NOW()
        LIMIT ${Math.max(1, Math.floor(limit))}
    ) capped
) due`

export const QUEUE_DEPTHS_SQL = `WITH RECURSIVE ${QUEUE_CLASSES_CTE}
SELECT c.queue_name, SUM(due.count) AS count,
       EXTRACT(EPOCH FROM NOW() - MIN(due.oldest))::float8 * 1000 AS oldest_due_age_ms
FROM queue_classes c
CROSS JOIN LATERAL (
    SELECT COUNT(*) AS count, MIN(j.scheduled) AS oldest FROM cyclotron_jobs j
    WHERE j.status = 'available' AND j.queue_name = c.queue_name AND j.priority = c.priority AND j.scheduled <= NOW()
) due
WHERE due.count > 0
GROUP BY c.queue_name`

const legacyCountWorkSql = (only: RowFilter): string => `SELECT COUNT(*)::int AS n FROM (
    SELECT 1 FROM cyclotron_jobs
    WHERE status = 'available' AND queue_name = $1 AND scheduled <= NOW() ${only('')}
    LIMIT $2
) sub`

const legacyDequeueJobsSql = (only: RowFilter): string => `WITH available AS (
    SELECT id FROM cyclotron_jobs
    WHERE status = 'available' AND queue_name = $1 AND scheduled <= NOW() ${only('')}
    ORDER BY priority ASC, scheduled ASC
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
${CLAIM_UPDATE}
FROM available
WHERE cyclotron_jobs.id = available.id
${CLAIM_RETURNING}`

export const FAIR_DEQUEUE_CANDIDATE_CAP = 1000

const OPAQUE_QUEUE_NAME = '(SELECT $1::text)'

const fairDequeueJobsSql = (only: RowFilter): string => `WITH RECURSIVE ${priorityClassesCte(OPAQUE_QUEUE_NAME)},
due AS MATERIALIZED (
    SELECT due.id, due.priority, due.dequeue_seq
    FROM (SELECT priority FROM priority_classes ORDER BY priority ASC) c
    CROSS JOIN LATERAL (
        SELECT j.id, j.priority, j.dequeue_seq FROM cyclotron_jobs j
        WHERE j.status = 'available' AND j.queue_name = ${OPAQUE_QUEUE_NAME} AND j.priority = c.priority AND j.scheduled <= NOW() ${only('j.')}
        ORDER BY j.scheduled ASC
        LIMIT ${FAIR_DEQUEUE_CANDIDATE_CAP} + 1
    ) due
    LIMIT ${FAIR_DEQUEUE_CANDIDATE_CAP} + 1
),
complete AS MATERIALIZED (
    SELECT COUNT(*) <= ${FAIR_DEQUEUE_CANDIDATE_CAP} AS all_due_rows FROM due
),
from_due AS (
    SELECT j.id
    FROM (SELECT id, priority, dequeue_seq FROM due ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST) d
    JOIN cyclotron_jobs j ON j.id = d.id
    WHERE (SELECT all_due_rows FROM complete)
      AND j.status = 'available' AND j.queue_name = ${OPAQUE_QUEUE_NAME} ${only('j.')}
    ORDER BY d.priority ASC, d.dequeue_seq ASC NULLS FIRST
    LIMIT $2
    FOR UPDATE OF j SKIP LOCKED
),
from_index AS (
    SELECT id FROM cyclotron_jobs
    WHERE NOT (SELECT all_due_rows FROM complete)
      AND status = 'available' AND queue_name = $1 AND scheduled <= NOW() ${only('')}
    ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
${CLAIM_UPDATE}
WHERE cyclotron_jobs.id = ANY(ARRAY(SELECT id FROM from_due UNION ALL SELECT id FROM from_index))
  AND cyclotron_jobs.scheduled <= NOW()
${CLAIM_RETURNING}`

const legacyFairDequeueJobsSql = (only: RowFilter): string => `WITH available AS (
    SELECT id FROM cyclotron_jobs
    WHERE status = 'available' AND queue_name = $1 AND scheduled <= NOW() ${only('')}
    ORDER BY priority ASC, dequeue_seq ASC NULLS FIRST
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
${CLAIM_UPDATE}
FROM available
WHERE cyclotron_jobs.id = available.id
${CLAIM_RETURNING}`

export type PollSql = {
    countWork: string
    dequeueJobs: string
    fairDequeueJobs: string
    legacyCountWork: string
    legacyDequeueJobs: string
    legacyFairDequeueJobs: string
}

const pollSql = (only: RowFilter): PollSql => ({
    countWork: countWorkSql(only),
    dequeueJobs: dequeueJobsSql(only),
    fairDequeueJobs: fairDequeueJobsSql(only),
    legacyCountWork: legacyCountWorkSql(only),
    legacyDequeueJobs: legacyDequeueJobsSql(only),
    legacyFairDequeueJobs: legacyFairDequeueJobsSql(only),
})

export const ANY_ROW_POLL_SQL = pollSql(anyRow)
export const plainRowPollSql = (queueName: string): PollSql => pollSql(emailRows(queueName, 'IS NULL'))
export const filesRowPollSql = (queueName: string): PollSql => pollSql(emailRows(queueName, 'IS NOT NULL'))
