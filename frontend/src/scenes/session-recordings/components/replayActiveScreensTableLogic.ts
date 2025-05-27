import { defaults, kea, key, listeners, path, props, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'

import type { replayActiveScreensTableLogicType } from './replayActiveScreensTableLogicType'

export interface ReplayActiveScreensTableLogicProps {
    scene?: 'templates' | 'filters' | 'replay-home'
}

export const replayActiveScreensTableLogic = kea<replayActiveScreensTableLogicType>([
    path(['scenes', 'session-recordings', 'components', 'replayActiveScreensTableLogic']),
    props({} as ReplayActiveScreensTableLogicProps),
    key((props) => props.scene || 'default'),
    defaults({
        countedScreens: [] as { screen: string; count: number }[],
    }),
    lazyLoaders(() => ({
        countedScreens: {
            loadCountedScreens: async (_, breakpoint): Promise<{ screen: string; count: number }[]> => {
                const q = hogql`
                    select cutQueryString(cutFragment(url)) as u, count(distinct session_id) as c
                    from (select session_id, arrayJoin(all_urls) as url
                          from raw_session_replay_events
                          where min_first_timestamp >= now() - toIntervalDay(7)
                            and min_first_timestamp <= now())
                    group by u
                    order by c desc limit 10
                `

                const qResponse = await api.query<HogQLQuery>({
                    kind: NodeKind.HogQLQuery,
                    query: q,
                })

                breakpoint()

                return (qResponse.results || []).map((row) => {
                    return {
                        screen: row[0] as string,
                        count: row[1] as number,
                    }
                }) as { screen: string; count: number }[]
            },
        },
    })),
    selectors(() => ({})),
    listeners(() => ({})),
])
