import { actions, connect, kea, listeners, path, props } from 'kea'
import api from 'lib/api'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ErrorTrackingGroup } from '~/queries/schema'

import type { errorTrackingDataNodeLogicType } from './errorTrackingDataNodeLogicType'
import { mergeGroups } from './utils'

export interface ErrorTrackingDataNodeLogicProps {
    query: DataNodeLogicProps['query']
    key: DataNodeLogicProps['key']
}

export const errorTrackingDataNodeLogic = kea<errorTrackingDataNodeLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingDataNodeLogic']),
    props({} as ErrorTrackingDataNodeLogicProps),

    connect(({ key, query }: ErrorTrackingDataNodeLogicProps) => ({
        values: [dataNodeLogic({ key, query }), ['response']],
        actions: [dataNodeLogic({ key, query }), ['setResponse']],
    })),

    actions({
        mergeGroups: (indexes: number[]) => ({ indexes }),
        assignGroup: (recordIndex: number, assigneeId: number | null) => ({
            recordIndex,
            assigneeId,
        }),
    }),

    listeners(({ values, actions }) => ({
        mergeGroups: async ({ indexes }) => {
            const results = values.response?.results as ErrorTrackingGroup[]

            const groups = results.filter((_, id) => indexes.includes(id))
            const primaryGroup = groups.shift()

            if (primaryGroup && groups.length > 0) {
                const mergingFingerprints = groups.map((g) => g.fingerprint)
                const mergedGroup = mergeGroups(primaryGroup, groups)

                // optimistically update local results
                actions.setResponse({
                    ...values.response,
                    results: results
                        // remove merged groups
                        .filter((_, id) => !indexes.includes(id))
                        .map((group) =>
                            // replace primary group
                            mergedGroup.fingerprint === group.fingerprint ? mergedGroup : group
                        ),
                })
                await api.errorTracking.merge(primaryGroup?.fingerprint, mergingFingerprints)
            }
        },
        assignGroup: async ({ recordIndex, assigneeId }) => {
            const response = values.response
            if (response) {
                const params = { assignee: assigneeId }
                const results = response.results as ErrorTrackingGroup[]
                const group = { ...results[recordIndex], ...params }
                results.splice(recordIndex, 1, group)
                // optimistically update local results
                actions.setResponse({ ...response, results: results })
                await api.errorTracking.update(group.fingerprint, params)
            }
        },
    })),
])
