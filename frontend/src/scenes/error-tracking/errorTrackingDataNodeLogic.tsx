import { actions, connect, kea, listeners, path, props, selectors } from 'kea'
import api from 'lib/api'
import posthog from 'posthog-js'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

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
        resolveIssues: (ids: string[]) => ({ ids }),
        assignIssues: (ids: string[], assignee: ErrorTrackingIssue['assignee']) => ({ ids, assignee }),
        assignIssue: (id: string, assignee: ErrorTrackingIssue['assignee']) => ({ id, assignee }),
    }),

    selectors({
        results: [(s) => [s.response], (response): ErrorTrackingIssue[] => (response ? response.results : [])],
    }),

    listeners(({ values, actions }) => ({
        mergeIssues: async ({ ids }) => {
            const { results } = values

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
                        .filter(({ id }) => !mergingIds.includes(id))
                        .map((issue) =>
                            // replace primary issue
                            mergedIssue.id === issue.id ? mergedIssue : issue
                        ),
                })
                posthog.capture('error_tracking_issue_merged', { primary: primaryIssue.id })
                await api.errorTracking.mergeInto(primaryIssue.id, mergingIds)
                actions.loadData(true)
            }
        },
        resolveIssues: async ({ ids }) => {
            const { results } = values

            // optimistically update local results
            actions.setResponse({
                ...values.response,
                // remove resolved issues
                results: results.filter(({ id }) => !ids.includes(id)),
            })
            posthog.capture('error_tracking_issue_bulk_resolve')
            await api.errorTracking.bulkResolve(ids)
            actions.loadData(true)
        },
        assignIssues: async ({ ids, assignee }) => {
            const { results } = values

            // optimistically update local results
            actions.setResponse({
                ...values.response,
                // remove resolved issues
                results: results.map((issue) =>
                    // replace primary issue
                    ids.includes(issue.id) ? { ...issue, assignee } : issue
                ),
            })
            posthog.capture('error_tracking_issue_bulk_assign')
            await api.errorTracking.bulkAssign(ids, assignee)
            actions.loadData(true)
        },
        assignIssue: async ({ id, assignee }) => {
            const response = values.response
            if (response) {
                const results = response.results as ErrorTrackingIssue[]
                const recordIndex = results.findIndex((r) => r.id === id)
                if (recordIndex > -1) {
                    const issue = { ...results[recordIndex], assignee }
                    results.splice(recordIndex, 1, issue)
                    // optimistically update local results
                    actions.setResponse({ ...response, results: results })
                    await api.errorTracking.assignIssue(issue.id, assignee)
                    actions.loadData(true)
                }
            }
        },
    })),
])
