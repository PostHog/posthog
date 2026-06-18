import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { signalsReportsMergePrCreate } from 'products/signals/frontend/generated/api'

import { SignalReport } from '../types'
import type { rapidReviewLogicType } from './rapidReviewLogicType'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './reportListLogic'

/** Grace period before a swiped-right merge actually fires, during which it can be undone. */
const MERGE_UNDO_MS = 5000

const PULLS_LIST_PROPS = { tabKey: 'pulls' as const, listParams: INBOX_FLAT_TAB_LIST_PARAMS.pulls }

function prLabel(report: SignalReport): string {
    const number = report.implementation_pr_url?.split('/').pop()
    return number ? `PR #${number}` : 'this PR'
}

function mergeToastId(reportId: string): string {
    return `rapid-merge-${reportId}`
}

/**
 * Drives "Rapid review" — the swipe deck over the Pull requests tab. Reuses the pulls
 * `reportListLogic` as the source of truth (so the list and deck stay in sync) and layers a
 * `processedIds` set on top: a card leaves the deck the moment it is swiped, and a merge is only
 * committed to GitHub after a short undo window. Archive = suppress; merge = merge the PR.
 */
export const rapidReviewLogic = kea<rapidReviewLogicType>([
    path(['scenes', 'inbox', 'logics', 'rapidReviewLogic']),
    connect(() => ({
        values: [reportListLogic(PULLS_LIST_PROPS), ['reports', 'reportsResponseLoading', 'isLoaded']],
        actions: [reportListLogic(PULLS_LIST_PROPS), ['loadReports', 'removeReport']],
    })),
    actions({
        markProcessed: (reportId: string) => ({ reportId }),
        unmarkProcessed: (reportId: string) => ({ reportId }),
        archiveCurrent: true,
        mergeCurrent: true,
        scheduleMerge: (report: SignalReport) => ({ report }),
        undoMerge: (reportId: string) => ({ reportId }),
        performMerge: (reportId: string) => ({ reportId }),
        resetDeck: true,
    }),
    reducers({
        // Reports swiped out of the deck. Archive stays here permanently (then drops from `reports`);
        // a pending merge stays until it commits, and is removed again on undo so the card returns.
        processedIds: [
            [] as string[],
            {
                markProcessed: (state, { reportId }) => (state.includes(reportId) ? state : [...state, reportId]),
                unmarkProcessed: (state, { reportId }) => state.filter((id) => id !== reportId),
                resetDeck: () => [],
            },
        ],
    }),
    selectors({
        deck: [
            (s) => [s.reports, s.processedIds],
            (reports: SignalReport[], processedIds: string[]): SignalReport[] =>
                reports.filter((report) => !processedIds.includes(report.id)),
        ],
        currentReport: [(s) => [s.deck], (deck: SignalReport[]): SignalReport | null => deck[0] ?? null],
        nextReport: [(s) => [s.deck], (deck: SignalReport[]): SignalReport | null => deck[1] ?? null],
        remainingCount: [(s) => [s.deck], (deck: SignalReport[]): number => deck.length],
    }),
    listeners(({ actions, values, cache }) => ({
        archiveCurrent: async () => {
            const report = values.currentReport
            if (!report) {
                return
            }
            // Optimistically drop the card; restore it if the suppress call fails.
            actions.markProcessed(report.id)
            try {
                await api.signalReports.setState(report.id, { state: 'suppressed' })
                actions.removeReport(report.id)
            } catch {
                actions.unmarkProcessed(report.id)
                lemonToast.error('Could not archive this report. Please try again.')
            }
        },
        mergeCurrent: () => {
            const report = values.currentReport
            if (!report) {
                return
            }
            actions.markProcessed(report.id)
            actions.scheduleMerge(report)
        },
        scheduleMerge: ({ report }) => {
            lemonToast.info(`Merging ${prLabel(report)} into GitHub…`, {
                toastId: mergeToastId(report.id),
                autoClose: MERGE_UNDO_MS,
                button: { label: 'Undo', action: () => actions.undoMerge(report.id) },
            })
            // Fire the merge once the undo window lapses; cancellable via the disposable key.
            cache.disposables.add(() => {
                const timer = setTimeout(() => actions.performMerge(report.id), MERGE_UNDO_MS)
                return () => clearTimeout(timer)
            }, report.id)
        },
        undoMerge: ({ reportId }) => {
            cache.disposables.dispose(reportId)
            actions.unmarkProcessed(reportId)
            lemonToast.dismiss(mergeToastId(reportId))
        },
        performMerge: async ({ reportId }) => {
            cache.disposables.dispose(reportId)
            try {
                const result = await signalsReportsMergePrCreate(String(getCurrentTeamId()), reportId)
                actions.removeReport(reportId)
                const suffix = result.merge_method === 'squash' ? ' (squash)' : ''
                lemonToast.success(`Merged${suffix} into GitHub`)
            } catch (error: any) {
                // "Attempt anyway": surface GitHub's rejection and return the card to the deck.
                actions.unmarkProcessed(reportId)
                const message = error?.data?.error ?? error?.detail ?? 'GitHub could not merge this pull request.'
                lemonToast.error(message)
            }
        },
    })),
])
