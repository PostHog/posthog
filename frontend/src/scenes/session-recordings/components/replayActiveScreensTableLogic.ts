import { defaults, kea, key, path, props } from 'kea'
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
                // we can't use the all_urls column yet :/
                // const q = hogql`
                //     select cutQueryString(cutFragment(url)) as u, count(distinct session_id) as c
                //     from (select session_id, arrayJoin(all_urls) as url
                //           from raw_session_replay_events
                //           where min_first_timestamp >= now() - toIntervalDay(7)
                //             and min_first_timestamp <= now())
                //     group by u
                //     order by c desc limit 10
                // `
                const q = hogql`
                    select cutQueryString(cutFragment(the_url)), count(distinct session_id) as c
                    from (with (select \`$session_id\` as session_id, properties.$current_url as url
                                from events
                                where timestamp >= now() - toIntervalDay(7)
                                  and timestamp <= now()
                                  and properties.$current_url is not null
                                  and properties.$current_url != '') as event_urls
                          select raw_session_replay_events.session_id, arrayJoin(groupArray(event_urls.url)) as the_url
                          from raw_session_replay_events
                              left join event_urls
                          on raw_session_replay_events.session_id = event_urls.session_id
                          where min_first_timestamp >= now() - toIntervalDay(7)
                            and min_first_timestamp <= now()
                            and raw_session_replay_events.session_id in (
                              select \`$session_id\`
                              from events
                              where timestamp >= now() - toIntervalDay(7)
                            and timestamp <= now()
                            and properties.$current_url is not null
                            and properties.$current_url != ''
                              )
                          group by raw_session_replay_events.session_id
                          having date_diff('second', min (min_first_timestamp), max (max_last_timestamp)) > 5000)
                    group by the_url
                    order by c desc
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
])
