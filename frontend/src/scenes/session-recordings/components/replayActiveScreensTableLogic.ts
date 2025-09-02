import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

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
                    SELECT
                cutQueryString(cutFragment(url)) as screen,
                count(distinct session_id) as count
            FROM (
                SELECT
                    session_id,
                    arrayJoin(any(all_urls)) as url
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= now() - interval 7 day
                  AND min_first_timestamp <= now()
                GROUP BY session_id
                HAVING date_diff('second', min(min_first_timestamp), max(max_last_timestamp)) > 5
            )
            GROUP BY screen
            ORDER BY count DESC
            LIMIT 10
                `

                const qResponse = await api.queryHogQL(q)

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
