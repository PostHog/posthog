import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { DismissalReasonValue } from '../utils/dismissalReasons'
import type { inboxBulkActionsLogicType } from './inboxBulkActionsLogicType'

/** Tally of a bulk operation that ran one request per selected report. */
interface BulkActionResult {
    successCount: number
    failureCount: number
}

function formatDismissSummary(result: BulkActionResult): string {
    const { successCount, failureCount } = result
    const pluralized = successCount === 1 ? 'report' : 'reports'
    if (failureCount === 0) {
        return `${successCount} ${pluralized} dismissed`
    }
    return `${successCount} ${pluralized} dismissed, ${failureCount} failed`
}

/**
 * Multi-select + bulk dismiss for the inbox report list. Mirrors desktop
 * `inboxReportSelectionStore` (selection state) and `useInboxBulkActions`
 * (bulk suppress via `updateSignalReportState`). Kept deliberately thin: shift /
 * range selection lives in the list component; this logic owns the id set and
 * the dismiss call.
 */
export const inboxBulkActionsLogic = kea<inboxBulkActionsLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxBulkActionsLogic']),

    actions({
        toggleReportSelection: (reportId: string) => ({ reportId }),
        setSelectedReportIds: (reportIds: string[]) => ({ reportIds }),
        selectAll: (reportIds: string[]) => ({ reportIds }),
        clearSelection: true,
        /** Suppress every selected report with the chosen reason/note, then clear. */
        bulkDismiss: (reason: DismissalReasonValue, note: string) => ({ reason, note }),
        bulkDismissSuccess: true,
        bulkDismissFailure: true,
    }),

    reducers({
        selectedReportIds: [
            [] as string[],
            {
                toggleReportSelection: (state, { reportId }) =>
                    state.includes(reportId) ? state.filter((id) => id !== reportId) : [...state, reportId],
                setSelectedReportIds: (_, { reportIds }) => Array.from(new Set(reportIds)),
                selectAll: (_, { reportIds }) => Array.from(new Set(reportIds)),
                clearSelection: () => [],
            },
        ],
        isDismissing: [
            false,
            {
                bulkDismiss: () => true,
                bulkDismissSuccess: () => false,
                bulkDismissFailure: () => false,
            },
        ],
    }),

    selectors({
        selectedCount: [
            (s) => [s.selectedReportIds],
            (selectedReportIds: string[]): number => selectedReportIds.length,
        ],
        hasSelection: [
            (s) => [s.selectedReportIds],
            (selectedReportIds: string[]): boolean => selectedReportIds.length > 0,
        ],
    }),

    listeners(({ actions, values }) => ({
        bulkDismiss: async ({ reason, note }) => {
            const reportIds = values.selectedReportIds
            if (reportIds.length === 0) {
                actions.bulkDismissFailure()
                return
            }
            const trimmedNote = note.trim().slice(0, 4000)
            const results = await Promise.allSettled(
                reportIds.map((id) =>
                    api.signalReports.setState(id, {
                        state: 'suppressed',
                        dismissal_reason: reason,
                        ...(trimmedNote ? { dismissal_note: trimmedNote } : {}),
                    })
                )
            )
            const successCount = results.filter((r) => r.status === 'fulfilled').length
            const result: BulkActionResult = {
                successCount,
                failureCount: results.length - successCount,
            }

            actions.clearSelection()

            if (result.failureCount > 0) {
                lemonToast.error(formatDismissSummary(result))
                actions.bulkDismissFailure()
                return
            }
            lemonToast.success(formatDismissSummary(result))
            actions.bulkDismissSuccess()
        },
    })),
])
