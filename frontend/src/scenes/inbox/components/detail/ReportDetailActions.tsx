import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconArchive, IconPullRequest, IconUndo } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../../types'
import { useReportArchive } from '../cards/useReportArchive'

/** Mirror desktop's `Inbox report action` analytics for detail-pane actions. */
function fireReportAction(report: SignalReport, action: 'create_pr', extras: Record<string, unknown> = {}): void {
    posthog.capture('Inbox report action', {
        report_id: report.id,
        report_title: report.title ?? null,
        priority: report.priority ?? null,
        actionability: report.actionability ?? null,
        action_type: action,
        surface: 'detail_pane',
        ...extras,
    })
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
 * Detail-pane actions: Archive (suppress the report out of the inbox, then return to the list)
 * and Create PR (opens an implementation task and navigates to it). Task creation/navigation is
 * owned by `inboxTaskKickoffLogic`; archiving reuses the shared `useReportArchive` dialog flow.
 */
export function ReportDetailActions({ report }: { report: SignalReport }): JSX.Element {
    const { isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport } = useActions(inboxTaskKickoffLogic)
    const { activeTab } = useValues(inboxSceneLogic)
    const [isRestoring, setIsRestoring] = useState(false)

    const showCreatePr = canCreateImplementationPr(report)
    const isArchived = report.status === SignalReportStatus.SUPPRESSED

    const { isArchiving, onArchiveClick } = useReportArchive({
        reportId: report.id,
        cardTitle: report.title ?? 'Untitled report',
        // Back to the list once archived – the suppressed report drops out on the list's refetch.
        onArchived: () => router.actions.push(urls.inbox(activeTab)),
    })

    const onRestoreClick = async (): Promise<void> => {
        // Prefer the mounted Archived list logic so it optimistically drops the row and fixes its
        // count + tab badge synchronously (it also fires the API call + toast). Navigate straight back.
        const archivedList = reportListLogic.findMounted({
            tabKey: 'archived',
            listParams: INBOX_FLAT_TAB_LIST_PARAMS.archived,
        })
        if (archivedList) {
            archivedList.actions.restoreReport(report.id)
            router.actions.push(urls.inbox(activeTab))
            return
        }
        // Fallback for a deep-linked detail with no mounted Archived list (e.g. cold load).
        setIsRestoring(true)
        try {
            await api.signalReports.setState(report.id, { state: 'potential' })
            lemonToast.success('Report restored to inbox')
            router.actions.push(urls.inbox(activeTab))
        } catch (error: any) {
            lemonToast.error(error?.detail || error?.message || 'Failed to restore report')
        } finally {
            setIsRestoring(false)
        }
    }

    // An already-archived report offers Restore instead of Archive (and no Create PR).
    if (isArchived) {
        return (
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
        )
    }

    return (
        <>
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
                        fireReportAction(report, 'create_pr')
                        createPrFromReport(report)
                    }}
                >
                    Create PR
                </LemonButton>
            )}
        </>
    )
}
