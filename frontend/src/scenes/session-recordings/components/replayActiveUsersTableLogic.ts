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
            counted_sessions AS (
                SELECT
                    session_id,
                    any(distinct_id) AS sess_di,
                    count() AS c
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= now() - interval 7 day
                  AND min_first_timestamp <= now()
                GROUP BY session_id
                HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
            ),
            session_persons AS (
                SELECT
                    $session_id as session_id,
                    any(person_id) as person_id,
                    any(person.properties) as pp
                FROM events
                WHERE timestamp >= now() - interval 7 day
                  AND timestamp <= now()
                  AND $session_id IN (SELECT session_id FROM counted_sessions)
                  AND event IN ('$pageview', '$screen', '$autocapture', '$feature_flag_called', '$pageleave', '$identify', '$web_vitals', '$set', 'Application Opened', 'Application Backgrounded')
                GROUP BY $session_id
            )
            SELECT
                sp.person_id,
                sp.pp,
                sum(cs.c) as total_count
            FROM counted_sessions cs
            INNER JOIN session_persons sp ON cs.session_id = sp.session_id
            WHERE sp.person_id IS NOT NULL
            GROUP BY sp.person_id, sp.pp
            ORDER BY total_count DESC
            LIMIT 10
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
