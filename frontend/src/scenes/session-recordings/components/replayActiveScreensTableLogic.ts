import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, ReplayActiveScreensQuery } from '~/queries/schema/schema-general'

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
                const query: ReplayActiveScreensQuery = {
                    kind: NodeKind.ReplayActiveScreensQuery,
                }

                const response = await api.query(query)

                breakpoint()

                return (response.results || []).map((result) => ({
                    screen: result.screen,
                    count: result.count,
                }))
            },
        },
    })),
])
