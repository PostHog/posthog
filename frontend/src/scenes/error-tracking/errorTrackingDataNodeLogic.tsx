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
        actions: [dataNodeLogic({ key, query }), ['setResponse', 'loadData']],
    })),

    actions({
        mergeIssues: (ids: string[]) => ({ ids }),
        assignIssue: (id: string, assigneeId: number | null) => ({ id, assigneeId }),
    }),

    listeners(({ values, actions }) => ({
        mergeIssues: async ({ ids }) => {
            const results = values.response?.results as ErrorTrackingIssue[]

            const issues = results.filter(({ id }) => ids.includes(id))
            const primaryIssue = issues.shift()

            if (primaryIssue && issues.length > 0) {
                const mergingIds = issues.map((g) => g.id)
                const mergedIssue = mergeIssues(primaryIssue, issues)

                // optimistically update local results
                actions.setResponse({
                    ...values.response,
                    results: results
                        // remove merged issues
                        .filter(({ id }) => !ids.includes(id))
                        .map((issue) =>
                            // replace primary issue
                            mergedIssue.id === issue.id ? mergedIssue : issue
                        ),
                })
                await api.errorTracking.mergeInto(primaryIssue.id, mergingIds)
                actions.loadData(true)
            }
        },
        assignIssue: async ({ id, assigneeId }) => {
            const response = values.response
            if (response) {
                const params = { assignee: assigneeId }
                const results = response.results as ErrorTrackingIssue[]
                const recordIndex = results.findIndex((r) => r.id === id)
                if (recordIndex > -1) {
                    const issue = { ...results[recordIndex], ...params }
                    results.splice(recordIndex, 1, issue)
                    // optimistically update local results
                    actions.setResponse({ ...response, results: results })
                    await api.errorTracking.updateIssue(issue.id, params)
                    actions.loadData(true)
                }
            }
        },
    })),
])
