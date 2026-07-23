import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type MouseEvent, useState } from 'react'

import { IconArchive, IconMessage, IconPullRequest, IconReceipt, IconUndo } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { signalsReportArtefactsCreate } from 'products/signals/frontend/generated/api'

import { captureInboxReportAction, captureInboxReportFeedback } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../../types'
import { useReportArchive } from '../cards/useReportArchive'
import { useReportRefund } from '../cards/useReportRefund'
import { openFeedbackReportDialog } from '../shell/FeedbackReportDialog'

/**
 * One detail-pane action, rendered either inline as a `LemonButton` (wide layouts) or as a
 * `LemonMenu` item (the "…" overflow on narrow layouts). Keeping actions as data lets both
 * surfaces share a single source of truth instead of duplicating the button JSX.
 */
export interface ReportDetailAction {
    key: string
    label: string
    icon: JSX.Element
    onClick: (event: MouseEvent) => void
    loading?: boolean
    tooltip?: string
    /** Renders the action disabled with this explanation (e.g. a PR past its refund window). */
    disabledReason?: string
}

/**
 * Should the Create PR action be offered? Mirrors desktop `canCreateImplementationPr` /
 * the server-side autostart rules: only when ready & actionable, or blocked on user input.
 */
function canCreateImplementationPr(report: SignalReport): boolean {
    if (report.implementation_pr_url) {
        return false
    }
    if (report.already_addressed === true) {
        return false
    }
    if (report.status === 'pending_input') {
        return true
    }
    if (report.status === 'ready') {
        return report.actionability != null && ACTIONABLE_ACTIONABILITY_VALUES.includes(report.actionability)
    }
    return false
}

/**
 * Detail-pane actions as data: Feedback (always), Archive/Restore, and Create PR. Discuss is
 * rendered separately as a standalone dropdown button (`DiscussReportButton`) since it opens a
 * question popover rather than firing on click. Task creation is owned by `inboxTaskKickoffLogic`;
 * archiving reuses the shared `useReportArchive` dialog flow. Callers render these inline or inside a menu.
 */
export function useReportDetailActions(report: SignalReport): ReportDetailAction[] {
    const { isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const { reportArchived } = useActions(inboxBulkActionsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { activeTab } = useValues(inboxSceneLogic)
    const { loadSelectedReport } = useActions(inboxSceneLogic)
    const [isRestoring, setIsRestoring] = useState(false)

    const showCreatePr = canCreateImplementationPr(report)
    const isArchived = report.status === SignalReportStatus.SUPPRESSED
    // Resolved reports are terminal – nothing to archive, restore, or kick off.
    const isResolved = report.status === SignalReportStatus.RESOLVED
    // Refund leaves a report in place only when a merged PR resolved it; anything else it archives
    // (so the open PR gets closed), which means the view has to navigate away. Mirrors the
    // `resolved_via_merged_pr` branch in the refund endpoint.
    const staysPutOnRefund = isResolved && report.implementation_pr_merged === true

    const { isArchiving, onArchiveClick } = useReportArchive({
        reportId: report.id,
        cardTitle: report.title ?? 'Untitled report',
        report,
        surface: 'detail_pane',
        // Once the suppress persists, broadcast so every mounted list reconciles against the server
        // (the report leaves Reports/Pull requests and joins Archived), then return to the list.
        onArchived: () => {
            reportArchived()
            router.actions.push(urls.inbox(activeTab))
        },
    })

    const { canRefund, refundDisabledReason, isRefunding, onRefundClick } = useReportRefund({
        report,
        surface: 'detail_pane',
        // Refunding archives the report server-side, so reconcile the lists the same way and
        // return to the list — except for resolved reports, which stay where they are.
        onRefunded: () => {
            reportArchived()
            if (!staysPutOnRefund) {
                router.actions.push(urls.inbox(activeTab))
            } else {
                // These reports stay on this page, so refetch: the fresh copy carries `refund`,
                // which surfaces the Refunded badge and drops Refund from the actions.
                loadSelectedReport({ id: report.id })
            }
        },
    })

    const refund: ReportDetailAction = {
        key: 'refund',
        label: 'Refund',
        icon: <IconReceipt />,
        loading: isRefunding,
        tooltip: "Refund this PR – you won't pay for it and it won't count toward your included PRs",
        disabledReason: refundDisabledReason ?? undefined,
        onClick: onRefundClick,
    }

    const onRestoreClick = async (): Promise<void> => {
        // Prefer the mounted Archived list logic so it optimistically drops the row and fixes its
        // count + tab badge synchronously (it also fires the API call + toast). Navigate straight back.
        const archivedList = reportListLogic.findMounted({
            tabKey: 'archived',
            listParams: INBOX_FLAT_TAB_LIST_PARAMS.archived,
        })
        if (archivedList) {
            // The list logic fires the `restore` analytics; just drive navigation here.
            archivedList.actions.restoreReport(report.id)
            router.actions.push(urls.inbox(activeTab))
            return
        }
        // Fallback for a deep-linked detail with no mounted Archived list (e.g. cold load).
        setIsRestoring(true)
        try {
            await api.signalReports.setState(report.id, { state: 'potential' })
            captureInboxReportAction({ report, actionType: 'restore', surface: 'detail_pane' })
            lemonToast.success('Report restored to inbox')
            router.actions.push(urls.inbox(activeTab))
        } catch (error: any) {
            lemonToast.error(error?.detail || error?.message || 'Failed to restore report')
        } finally {
            setIsRestoring(false)
        }
    }

    // Feedback is always available – it never changes the report's state, just records what the
    // user thinks of it (and its PR), so it stays even for resolved/archived reports.
    const feedback: ReportDetailAction = {
        key: 'feedback',
        label: 'Feedback',
        icon: <IconMessage />,
        tooltip: 'Tell us how useful this report was',
        onClick: () =>
            openFeedbackReportDialog({
                reportTitle: report.title ?? 'Untitled report',
                onConfirm: async ({ sentiment, note }) => {
                    // Persist on the report (as a `feedback` artefact) so agents can read it and
                    // learn from it on later runs, not just the analytics event.
                    try {
                        if (currentTeamId == null) {
                            throw new Error('No team in context')
                        }
                        await signalsReportArtefactsCreate(String(currentTeamId), report.id, {
                            artefact_type: 'feedback',
                            content: { sentiment, ...(note ? { note } : {}) },
                        })
                    } catch (error: any) {
                        lemonToast.error(error?.detail || error?.error || error?.message || 'Failed to send feedback')
                        throw error // keep the dialog open so the user can retry
                    }
                    captureInboxReportFeedback({ report, sentiment, note, surface: 'detail_pane' })
                    lemonToast.success('Thanks for the feedback')
                },
            }),
    }

    // A resolved report is terminal – its PR already merged, so only feedback and Discuss (rendered
    // separately) apply. The PR can still be refunded (auto-approved by design; the weekly review
    // watches refunded-then-merged).
    if (isResolved) {
        return [feedback, ...(canRefund ? [refund] : [])]
    }

    // An already-archived report offers Restore instead of Archive (and no Create PR). A refunded
    // report can't be restored (its PR can never be billed again), so Restore is hidden for it; an
    // archived-but-still-charged report can still be refunded.
    if (isArchived) {
        return [
            feedback,
            ...(canRefund ? [refund] : []),
            ...(report.refund
                ? []
                : [
                      {
                          key: 'restore',
                          label: 'Restore',
                          icon: <IconUndo />,
                          loading: isRestoring,
                          tooltip: 'Restore this report to your inbox',
                          onClick: () => void onRestoreClick(),
                      },
                  ]),
        ]
    }

    const actions: ReportDetailAction[] = [
        feedback,
        {
            key: 'archive',
            label: 'Archive',
            icon: <IconArchive />,
            loading: isArchiving,
            tooltip: 'Archive this report out of your inbox',
            onClick: onArchiveClick,
        },
        ...(canRefund ? [refund] : []),
    ]

    if (showCreatePr) {
        actions.push({
            key: 'create-pr',
            label: 'Create PR',
            icon: <IconPullRequest />,
            loading: isCreatingPr,
            tooltip: 'Have Self-driving open a pull request for this report',
            onClick: () => {
                captureInboxReportAction({ report, actionType: 'create_pr', surface: 'detail_pane' })
                createPrFromReport(report)
            },
        })
    }

    return actions
}
