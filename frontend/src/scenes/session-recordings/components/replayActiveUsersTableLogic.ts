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
                    select p, any (pp), count () as c
                    from (
                        select any (person_id) as p, any (person.properties) as pp
                        from raw_session_replay_events
                        where min_first_timestamp <= now()
                        and min_first_timestamp >= now() - toIntervalDay(7)
                        group by session_id
                        having date_diff('second', min (min_first_timestamp), max (max_last_timestamp)) > 5000
                        ) as q
                    group by p
                    order by c desc
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
