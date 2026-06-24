import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconArchive, IconMessage, IconPullRequest, IconUndo } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

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
 * Detail-pane actions: Archive (suppress the report out of the inbox, then return to the list)
 * and Create PR (opens an implementation task and navigates to it). Task creation/navigation is
 * owned by `inboxTaskKickoffLogic`; archiving reuses the shared `useReportArchive` dialog flow.
 */
export function ReportDetailActions({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
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
    const feedbackButton = (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconMessage />}
            tooltip="Tell us how useful this report was"
            onClick={() =>
                openFeedbackReportDialog({
                    reportTitle: report.title ?? 'Untitled report',
                    onConfirm: ({ sentiment, note }) => {
                        captureInboxReportFeedback({ report, sentiment, note, surface: 'detail_pane' })
                        lemonToast.success('Thanks for the feedback')
                    },
                })
            }
        >
            Feedback
        </LemonButton>
    )

    // A resolved report is terminal – its PR already merged, so only feedback applies.
    if (isResolved) {
        return feedbackButton
    }

    // An already-archived report offers Restore instead of Archive (and no Create PR).
    if (isArchived) {
        return (
            <>
                {feedbackButton}
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconUndo />}
                    loading={isRestoring}
                    tooltip="Restore this report to your inbox"
                    onClick={() => void onRestoreClick()}
                >
                    Restore
                </LemonButton>
            </>
        )
    }

    return (
        <>
            {feedbackButton}
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconArchive />}
                loading={isArchiving}
                tooltip="Archive this report out of your inbox"
                onClick={onArchiveClick}
            >
                Archive
            </LemonButton>

            {showCreatePr && (
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconPullRequest />}
                    loading={isCreatingPr}
                    tooltip="Have Self-driving open a pull request for this report"
                    onClick={() => {
                        captureInboxReportAction({ report, actionType: 'create_pr', surface: 'detail_pane' })
                        createPrFromReport(report)
                    }}
                >
                    Create PR
                </LemonButton>
            )}
        </>
    )
}
