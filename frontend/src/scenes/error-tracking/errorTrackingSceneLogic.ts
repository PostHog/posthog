import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { ErrorTrackingOrder } from '~/queries/schema'
import { ErrorTrackingGroupType, InsightLogicProps } from '~/types'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    actions({
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
        loadGroups: (fingerprints: string[]) => ({ fingerprints }),
    }),
    reducers({
        order: [
            'last_seen' as ErrorTrackingOrder,
            { persist: true },
            {
                setOrder: (_, { order }) => order,
            },
        ],
    }),

    selectors(({ actions }) => ({
        insightProps: [
            () => [],
            (): InsightLogicProps => {
                return {
                    dashboardItemId: 'new-error-tracking',
                    onData: (data) => {
                        const results = data?.results as any[][]
                        const fingerprints = results.map((r) => r[1])

                        const uniqueFingerprints = fingerprints.filter(
                            (value, index, arr) => arr.indexOf(value) === index
                        )

                        if (uniqueFingerprints.length > 0) {
                            actions.loadGroups(uniqueFingerprints)
                        } else {
                            // TODO: remove once happy it works
                            actions.loadGroups(['hello'])
                        }
                    },
                }
            },
        ],
    })),

    loaders(({ values }) => ({
        groups: [
            [] as ErrorTrackingGroupType[],
            {
                loadGroups: async ({ fingerprints }) => {
                    const response = await api.error_tracking.list({ fingerprints: fingerprints })
                    return [...values.groups, ...response.results]
                },
            },
        ],
    })),
])
