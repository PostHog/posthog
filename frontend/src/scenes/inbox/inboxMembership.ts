// Port of desktop `@posthog/core/inbox/reportMembership`. Pure functions that
// decide which tab a report belongs to and how the scope filter applies.
// Keep behaviour identical to desktop — this is the source of truth for tab IA.

import {
    EMPTY_TAB_COUNTS,
    InboxScope,
    INBOX_SCOPE_ENTIRE_PROJECT,
    InboxTabCounts,
    InboxTabKey,
    SignalReport,
    SignalReportStatus,
} from './types'

/**
 * Statuses out of the inbox entirely (user-suppressed or removed). `failed` is
 * NOT here: failed runs surface in the Runs tab's recently-finished section.
 */
const INBOX_EXCLUDED_STATUSES = new Set<SignalReportStatus>([SignalReportStatus.SUPPRESSED, SignalReportStatus.DELETED])

export function isExcludedFromInbox(report: SignalReport): boolean {
    return INBOX_EXCLUDED_STATUSES.has(report.status)
}

export function teammateInboxScope(uuid: string): InboxScope {
    return `teammate:${uuid}`
}

export function parseTeammateInboxScope(scope: InboxScope): string | null {
    if (!scope.startsWith('teammate:')) {
        return null
    }
    const uuid = scope.slice('teammate:'.length).trim()
    return uuid || null
}

export function isTeammateInboxScope(scope: InboxScope): scope is `teammate:${string}` {
    return parseTeammateInboxScope(scope) != null
}

export function inboxScopeTriggerLabel(scope: InboxScope, teammateName?: string | null): string {
    if (scope === 'for-you') {
        return 'For you'
    }
    if (scope === INBOX_SCOPE_ENTIRE_PROJECT) {
        return 'Entire project'
    }
    return teammateName?.trim() || 'Teammate'
}

export function matchesInboxScope(report: SignalReport, scope: InboxScope): boolean {
    if (isExcludedFromInbox(report)) {
        return false
    }
    if (scope === INBOX_SCOPE_ENTIRE_PROJECT) {
        return true
    }
    if (isTeammateInboxScope(scope)) {
        return true
    }
    return report.is_suggested_reviewer === true
}

/** PR tab membership: an agent shipped a draft PR and the report is still in-inbox. */
export function isPullRequestReport(report: SignalReport): boolean {
    return !!report.implementation_pr_url && !isExcludedFromInbox(report)
}

const QUEUED_RUN_STATUSES = new Set<SignalReportStatus>([SignalReportStatus.POTENTIAL, SignalReportStatus.CANDIDATE])
const LIVE_RUN_STATUSES = new Set<SignalReportStatus>([
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.PENDING_INPUT,
])
const FINISHED_RUN_STATUSES = new Set<SignalReportStatus>([SignalReportStatus.READY, SignalReportStatus.FAILED])

export function isQueuedRunReport(report: SignalReport): boolean {
    return QUEUED_RUN_STATUSES.has(report.status)
}

export function isLiveRunReport(report: SignalReport): boolean {
    return LIVE_RUN_STATUSES.has(report.status)
}

export function isFinishedRunReport(report: SignalReport): boolean {
    return FINISHED_RUN_STATUSES.has(report.status)
}

/** Runs-tab count chip + cross-tab exclusion: only "in motion" runs (queued or live). */
export function isAgentRunReport(report: SignalReport): boolean {
    return isQueuedRunReport(report) || isLiveRunReport(report)
}

export function isReportTabReport(report: SignalReport): boolean {
    if (isExcludedFromInbox(report)) {
        return false
    }
    if (report.status === SignalReportStatus.FAILED) {
        return false // failed runs live in the Runs tab only
    }
    if (isPullRequestReport(report)) {
        return false
    }
    if (isAgentRunReport(report)) {
        return false
    }
    return true
}

export function matchesReviewerScope(report: SignalReport, scope: InboxScope): boolean {
    return matchesInboxScope(report, scope)
}

export function computeInboxTabCounts(reports: SignalReport[], scope: InboxScope): InboxTabCounts {
    const counts: InboxTabCounts = { ...EMPTY_TAB_COUNTS }
    for (const report of reports) {
        if (isExcludedFromInbox(report)) {
            continue
        }
        // Runs count is project-wide: reviewer assignment is an output of research,
        // so the For-you / teammate filter is meaningless until a report reaches a
        // downstream tab.
        if (isAgentRunReport(report)) {
            counts.runs += 1
        }
        if (!matchesReviewerScope(report, scope)) {
            continue
        }
        if (isPullRequestReport(report)) {
            counts.pulls += 1
        }
        if (isReportTabReport(report)) {
            counts.reports += 1
        }
    }
    return counts
}

/** Reports visible in a given tab under a given scope. */
export function reportsForTab(reports: SignalReport[], tab: InboxTabKey, scope: InboxScope): SignalReport[] {
    return reports.filter((report) => {
        if (isExcludedFromInbox(report)) {
            return false
        }
        if (tab === 'runs') {
            // Runs is project-wide and includes finished (ready/failed) runs as history.
            return isAgentRunReport(report) || isFinishedRunReport(report)
        }
        if (!matchesReviewerScope(report, scope)) {
            return false
        }
        if (tab === 'pulls') {
            return isPullRequestReport(report)
        }
        return isReportTabReport(report)
    })
}
