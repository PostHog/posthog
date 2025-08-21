import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { PersonType } from '~/types'

import type { replayActiveUsersTableLogicType } from './replayActiveUsersTableLogicType'

export interface ReplayActiveUsersTableLogicProps {
    scene?: 'templates' | 'filters' | 'replay-home'
}

export const replayActiveUsersTableLogic = kea<replayActiveUsersTableLogicType>([
    path(['scenes', 'session-recordings', 'components', 'replayActiveUsersTableLogic']),
    props({} as ReplayActiveUsersTableLogicProps),
    key((props) => props.scene || 'default'),
    defaults({
        countedUsers: [] as { person: PersonType; count: number }[],
    }),
    lazyLoaders(() => ({
        countedUsers: {
            loadCountedUsers: async (_, breakpoint): Promise<{ person: PersonType; count: number }[]> => {
                const q = hogql`
                  WITH
session_distinct_ids AS (
    SELECT any(distinct_id) AS di
    FROM raw_session_replay_events
    WHERE min_first_timestamp <= now()
      AND min_first_timestamp >= now() - toIntervalDay(7)
    GROUP BY session_id
    HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
),

person_ids as (
  SELECT
    p.id AS person_id, p.properties as person_properties, p.pdi.distinct_id as the_pdi
  FROM persons p
  where p.pdi.distinct_id in (select di from session_distinct_ids)
),

counted_sessions AS (
    SELECT di AS sess_di, count() AS c
    FROM (
        SELECT any(distinct_id) AS di
        FROM raw_session_replay_events
        WHERE min_first_timestamp <= now()
          AND min_first_timestamp >= now() - toIntervalDay(7)
          AND distinct_id IN (SELECT di FROM session_distinct_ids)
        GROUP BY session_id
        HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
    )
    GROUP BY sess_di
    ORDER BY c DESC
    LIMIT 5000
)
SELECT
    pi.person_id,
    pi.person_properties,
    cs.c AS count
FROM counted_sessions AS cs
ANY LEFT JOIN person_ids AS pi
    ON pi.the_pdi = cs.sess_di
  order by count desc
  limit 10
                `

                const qResponse = await api.queryHogQL(q)

                breakpoint()

                return (qResponse.results || []).map((row) => {
                    return {
                        person: { id: row[0] as string, properties: JSON.parse(row[1]) as Record<string, any> },
                        count: row[2] as number,
                    }
                }) as { person: PersonType; count: number }[]
            },
        },
    })),
])
