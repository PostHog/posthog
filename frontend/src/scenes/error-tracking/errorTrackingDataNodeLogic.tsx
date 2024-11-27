import { actions, connect, kea, listeners, path, props } from 'kea'
import api from 'lib/api'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ErrorTrackingIssue } from '~/queries/schema'

import type { errorTrackingDataNodeLogicType } from './errorTrackingDataNodeLogicType'
import { mergeIssues } from './utils'

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
        mergeIssues: (indexes: number[]) => ({ indexes }),
        assignIssue: (recordIndex: number, assigneeId: number | null) => ({
            recordIndex,
            assigneeId,
        }),
    }),

    listeners(({ values, actions }) => ({
        mergeIssues: async ({ indexes }) => {
            const results = values.response?.results as ErrorTrackingIssue[]

            const issues = results.filter((_, id) => indexes.includes(id))
            const primaryIssue = issues.shift()

            if (primaryIssue && issues.length > 0) {
                const mergingIds = issues.map((g) => g.id)
                const mergedIssue = mergeIssues(primaryIssue, issues)

                // optimistically update local results
                actions.setResponse({
                    ...values.response,
                    results: results
                        // remove merged issues
                        .filter((_, id) => !indexes.includes(id))
                        .map((issue) =>
                            // replace primary issue
                            mergedIssue.id === issue.id ? mergedIssue : issue
                        ),
                })
                await api.errorTracking.merge(primaryIssue.id, mergingIds)
            }
        },
        assignIssue: async ({ recordIndex, assigneeId }) => {
            const response = values.response
            if (response) {
                const params = { assignee: assigneeId }
                const results = response.results as ErrorTrackingIssue[]
                const issue = { ...results[recordIndex], ...params }
                results.splice(recordIndex, 1, issue)
                // optimistically update local results
                actions.setResponse({ ...response, results: results })
                await api.errorTracking.updateIssue(issue.id, params)
            }
        },
    })),
])
