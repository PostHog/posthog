import { EMAIL_TRANSACTIONAL_QUEUE } from '../messaging/email-queues'

/**
 * Every table name that reaches SQL is one of these constants, chosen by queue
 * name — never a value from input, because they are interpolated into query text
 * rather than bound as parameters.
 */
export const CYCLOTRON_JOBS_TABLE = 'cyclotron_jobs'
export const CYCLOTRON_JOBS_TRANSACTIONAL_TABLE = 'cyclotron_jobs_transactional'

export const CYCLOTRON_JOB_TABLES = [CYCLOTRON_JOBS_TABLE, CYCLOTRON_JOBS_TRANSACTIONAL_TABLE] as const
export type CyclotronJobTable = (typeof CYCLOTRON_JOB_TABLES)[number]

export function tableForQueue(queueName: string): CyclotronJobTable {
    return queueName === EMAIL_TRANSACTIONAL_QUEUE ? CYCLOTRON_JOBS_TRANSACTIONAL_TABLE : CYCLOTRON_JOBS_TABLE
}

/** Both tables carry the same set, which is what lets one INSERT ... SELECT move a row. */
export const CYCLOTRON_JOB_COLUMNS = [
    'id',
    'team_id',
    'function_id',
    'queue_name',
    'status',
    'priority',
    'scheduled',
    'created',
    'lock_id',
    'last_heartbeat',
    'janitor_touch_count',
    'transition_count',
    'last_transition',
    'parent_run_id',
    'state',
    'distinct_id',
    'person_id',
    'action_id',
    'dequeue_seq',
    'cancel_requested_at',
] as const
