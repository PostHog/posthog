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
            -- get the session ids for any recorded sessions in the last 7 days
            recorded_sessions AS (
                SELECT session_id
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= now() - interval 7 day
                  AND min_first_timestamp <= now()
                GROUP BY session_id
                HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
            ),
            -- way faster to get person props from the events table
            -- so get the mapping of person_id/person_properties to session_id
            -- from the events table that has the same session_id as the recorded sessions
            session_persons AS (
                SELECT
                    $session_id as session_id,
                    any(person_id) as person_id,
                    any(person.properties) as pp
                FROM events
                WHERE timestamp >= now() - interval 7 day
                  AND timestamp <= now()
                  AND $session_id IN (SELECT session_id FROM recorded_sessions)
                  -- including events when querying the events table is always _much_ faster,
                  -- but we don't know what events an account will have
                  -- so we just include the most common ones
                  -- this won't work for everyone but then that's try with the poorly performing query
                  -- that this replaces, so it's at least no worse 🙈
                  AND event IN ('$pageview', '$screen', '$autocapture', '$feature_flag_called', '$pageleave', '$identify', '$web_vitals', '$set', 'Application Opened', 'Application Backgrounded')
                  -- exclude anonymous users since we don't care if user "anonymous" watched a gajillion recordings
                  AND (properties.$process_person_profile = true or properties.$is_identified = true)
                GROUP BY $session_id
            )
            -- now we can count the distinct sessions per person
            SELECT
                sp.person_id,
                sp.pp,
                count(distinct sp.session_id) as total_count
            FROM session_persons sp 
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
