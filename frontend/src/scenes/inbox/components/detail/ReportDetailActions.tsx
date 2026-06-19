import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconArchive, IconPullRequest } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { ACTIONABLE_ACTIONABILITY_VALUES, SignalReport } from '../../types'
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

    const showCreatePr = canCreateImplementationPr(report)

    const { isArchiving, onArchiveClick } = useReportArchive({
        reportId: report.id,
        cardTitle: report.title ?? 'Untitled report',
        // Back to the list once archived – the suppressed report drops out on the list's refetch.
        onArchived: () => router.actions.push(urls.inbox(activeTab)),
    })

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
