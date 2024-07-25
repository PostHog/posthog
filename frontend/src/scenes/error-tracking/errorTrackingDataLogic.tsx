import { actions, connect, kea, listeners, path, props } from 'kea'
import api from 'lib/api'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ErrorTrackingGroup } from '~/queries/schema'

import type { errorTrackingDataLogicType } from './errorTrackingDataLogicType'
import { mergeGroups } from './utils'

export interface ErrorTrackingDataLogicProps {
    query: DataNodeLogicProps['query']
    key: DataNodeLogicProps['key']
}

export const errorTrackingDataLogic = kea<errorTrackingDataLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingDataLogic']),
    props({} as ErrorTrackingDataLogicProps),

    connect(({ key, query }: ErrorTrackingDataLogicProps) => ({
        values: [dataNodeLogic({ key, query }), ['response']],
        actions: [dataNodeLogic({ key, query }), ['setResponse']],
    })),

    actions({
        mergeGroups: (fingerprints: string[]) => ({ fingerprints }),
        assignGroup: (recordIndex: number, assigneeId: number | null) => ({
            recordIndex,
            assigneeId,
        }),
    }),

    listeners(({ values, actions }) => ({
        mergeGroups: async ({ fingerprints }) => {
            const results = values.response?.results as ErrorTrackingGroup[]

            const groups = results.filter((g) => fingerprints.includes(g.fingerprint))
            const primaryGroup = groups.shift()

            if (primaryGroup && groups.length > 0) {
                const mergingFingerprints = groups.map((g) => g.fingerprint)
                const mergedGroup = mergeGroups(primaryGroup, groups)

                // optimistically update local results
                actions.setResponse({
                    ...values.response,
                    results: results
                        // remove merged groups
                        .filter((group) => !mergingFingerprints.includes(group.fingerprint))
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
                const results = values.response?.results as ErrorTrackingGroup[]
                const group = { ...results[recordIndex], ...params }
                results.splice(recordIndex, 1, group)
                // optimistically update local results
                actions.setResponse({ ...response, results: results })
                await api.errorTracking.update(group.fingerprint, params)
            }
        },
    })),
])
