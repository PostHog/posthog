import { actions, kea, listeners, path } from 'kea'
import api from 'lib/api'
import posthog from 'posthog-js'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import type { issueActionsLogicType } from './issueActionsLogicType'

export const issueActionsLogic = kea<issueActionsLogicType>([
    path(['scenes', 'error-tracking', 'issueActionsLogic']),

    actions({
        mergeIssues: (ids: string[]) => ({ ids }),
        resolveIssues: (ids: string[]) => ({ ids }),
        suppressIssues: (ids: string[]) => ({ ids }),
        activateIssues: (ids: string[]) => ({ ids }),
        assignIssues: (ids: string[], assignee: ErrorTrackingIssue['assignee']) => ({ ids, assignee }),
        assignIssue: (id: string, assignee: ErrorTrackingIssue['assignee']) => ({ id, assignee }),

        mutationSuccess: () => {},
        mutationFailure: (error: unknown) => ({ error }),
    }),

    listeners(({ actions }) => {
        async function runMutation(cb: () => Promise<void>): Promise<void> {
            try {
                await cb()
                actions.mutationSuccess()
            } catch (e: unknown) {
                actions.mutationFailure(e)
            }
        }
        return {
            mergeIssues: async ({ ids }) => {
                const [firstId, ...otherIds] = ids
                if (firstId && otherIds.length > 0) {
                    await runMutation(async () => {
                        posthog.capture('error_tracking_issue_merged', { primary: firstId })
                        await api.errorTracking.mergeInto(firstId, otherIds)
                    })
                }
            },
            resolveIssues: async ({ ids }) => {
                await runMutation(async () => {
                    posthog.capture('error_tracking_issue_bulk_resolve')
                    await api.errorTracking.bulkMarkStatus(ids, 'resolved')
                })
            },
            suppressIssues: async ({ ids }) => {
                await runMutation(async () => {
                    posthog.capture('error_tracking_issue_bulk_suppress')
                    await api.errorTracking.bulkMarkStatus(ids, 'suppressed')
                })
            },
            activateIssues: async ({ ids }) => {
                await runMutation(async () => {
                    posthog.capture('error_tracking_issue_bulk_activate')
                    await api.errorTracking.bulkMarkStatus(ids, 'active')
                })
            },
            assignIssues: async ({ ids, assignee }) => {
                await runMutation(async () => {
                    posthog.capture('error_tracking_issue_bulk_assign')
                    await api.errorTracking.bulkAssign(ids, assignee)
                })
            },
            assignIssue: async ({ id, assignee }) => {
                await runMutation(async () => {
                    posthog.capture('error_tracking_issue_assign')
                    await api.errorTracking.assignIssue(id, assignee)
                })
            },
        }
    }),
])
