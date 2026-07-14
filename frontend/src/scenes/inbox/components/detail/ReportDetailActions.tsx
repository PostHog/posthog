import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type MouseEvent, useState } from 'react'

import { IconArchive, IconCheckCircle, IconMessage, IconPullRequest, IconUndo } from '@posthog/icons'
import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { captureInboxReportAction, captureInboxReportFeedback } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../../types'
import { useReportArchive } from '../cards/useReportArchive'
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
 * Detail-pane actions as data: Feedback (always), Archive/Restore, and Create PR. Task
 * creation/navigation is owned by `inboxTaskKickoffLogic`; archiving reuses the shared
 * `useReportArchive` dialog flow. Callers render these inline or inside a menu.
 */
export function useReportDetailActions(report: SignalReport): ReportDetailAction[] {
    const { isCreatingPr, isMergingPr } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport, mergePrFromReport } = useActions(inboxTaskKickoffLogic)
    const { reportArchived } = useActions(inboxBulkActionsLogic)
    const { activeTab } = useValues(inboxSceneLogic)
    const [isRestoring, setIsRestoring] = useState(false)

    const showCreatePr = canCreateImplementationPr(report)
    const isArchived = report.status === SignalReportStatus.SUPPRESSED
    // Resolved reports are terminal (their implementation PR merged) – nothing to archive, restore, or kick off.
    const isResolved = report.status === SignalReportStatus.RESOLVED

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
                onConfirm: ({ sentiment, note }) => {
                    captureInboxReportFeedback({ report, sentiment, note, surface: 'detail_pane' })
                    lemonToast.success('Thanks for the feedback')
                },
            }),
    }

    // A resolved report is terminal – its PR already merged, so only feedback applies.
    if (isResolved) {
        return [feedback]
    }

    // An already-archived report offers Restore instead of Archive (and no Create PR).
    if (isArchived) {
        return [
            feedback,
            {
                key: 'restore',
                label: 'Restore',
                icon: <IconUndo />,
                loading: isRestoring,
                tooltip: 'Restore this report to your inbox',
                onClick: () => void onRestoreClick(),
            },
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

    // Offer Merge PR once an implementation PR exists (and the report isn't resolved/suppressed —
    // those cases returned above). GitHub's own merge rules are the guardrail: an unmergeable /
    // already-merged / closed PR is surfaced as a clean error on click rather than pre-hidden here.
    if (report.implementation_pr_url) {
        actions.push({
            key: 'merge-pr',
            label: 'Merge PR',
            icon: <IconCheckCircle />,
            loading: isMergingPr,
            tooltip: "Squash-merge this report's pull request on GitHub",
            onClick: () => {
                // Merging ships code, so confirm first — mirrors the guardrail on other state-changing actions.
                LemonDialog.open({
                    title: 'Merge pull request?',
                    description:
                        "This squash-merges the report's pull request on GitHub. It can't be undone from here.",
                    primaryButton: {
                        children: 'Merge PR',
                        onClick: () => {
                            captureInboxReportAction({ report, actionType: 'merge_pr', surface: 'detail_pane' })
                            mergePrFromReport(report)
                        },
                    },
                    secondaryButton: { children: 'Cancel' },
                })
            },
        })
    }

    return actions
}
