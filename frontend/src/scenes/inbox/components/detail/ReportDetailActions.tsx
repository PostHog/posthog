import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type MouseEvent, useState } from 'react'

import { IconArchive, IconMessage, IconPullRequest, IconUndo } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../../logics/reportListLogic'
import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport, SignalReportStatus } from '../../types'
import { useReportArchive } from '../cards/useReportArchive'

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
 * Detail-pane actions as data: Discuss (always), Archive/Restore, and Create PR. Task
 * creation/navigation is owned by `inboxTaskKickoffLogic`; archiving reuses the shared
 * `useReportArchive` dialog flow. Callers render these inline or inside a menu.
 */
export function useReportDetailActions(report: SignalReport): ReportDetailAction[] {
    const { isCreatingPr, isDiscussing } = useValues(inboxTaskKickoffLogic)
    const { createPrFromReport, discussReport } = useActions(inboxTaskKickoffLogic)
    const { primaryTask } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
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

    // Discuss is always available – it never changes the report's state, it just opens a
    // conversation with the agent, so it stays even for resolved/archived reports. When the report
    // already has a linked run (e.g. the task that opened its PR), jump straight into that
    // conversation so guidance reaches the agent already on the job; otherwise kick off a fresh
    // research task seeded from the report.
    const discuss: ReportDetailAction = {
        key: 'discuss',
        label: 'Discuss',
        icon: <IconMessage />,
        loading: isDiscussing,
        tooltip: primaryTask
            ? 'Continue the conversation with the agent working on this report'
            : 'Ask the agent about this report',
        onClick: () => {
            captureInboxReportAction({ report, actionType: 'discuss', surface: 'detail_pane' })
            if (primaryTask) {
                router.actions.push(urls.taskDetail(primaryTask.task.id))
                return
            }
            discussReport(report)
        },
    }

    // A resolved report is terminal – its PR already merged, so only Discuss applies.
    if (isResolved) {
        return [discuss]
    }

    // An already-archived report offers Restore instead of Archive (and no Create PR).
    if (isArchived) {
        return [
            discuss,
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
        discuss,
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

    return actions
}
