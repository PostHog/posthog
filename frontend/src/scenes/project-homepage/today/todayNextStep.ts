import { fullName } from 'lib/utils/strings'

import { buildReportImplementationPrompt } from 'products/signals/frontend/inbox/components/detail/buildReportImplementationPrompt'
import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type { SignalReport } from 'products/signals/frontend/inbox/types'
import { canResolveReport } from 'products/signals/frontend/inbox/utils/reportActions'
import { parsePrUrlParts, safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'
import { primaryReportPullRequest } from 'products/signals/frontend/inbox/utils/reportPullRequests'
import type { PullRequestLinkApi } from 'products/today/frontend/generated/api.schemas'

import { shortDate } from './todayProse'

export type TodayPrimaryAction =
    | { kind: 'review'; url: string; label: string }
    | { kind: 'open_task'; label: string; taskId: string; runId: string }
    | { kind: 'start' }

interface TodayNextStep {
    primary: TodayPrimaryAction | null
    note: string | null
    taskPickedUp: boolean
}

interface TodayNextStepContext {
    namedPullRequest: PullRequestLinkApi | null
    solutionNamesPullRequest: boolean
    slotClaimed: boolean
    runningTask: { taskId: string; runId: string } | null
}

const START: TodayPrimaryAction = { kind: 'start' }
const REVIEW_NOTES: Record<string, string> = {
    approved: 'Approved and ready to merge.',
    changes_requested: 'A reviewer asked for changes.',
}

function reviewLabel(url: string, draft: boolean): string {
    const number = parsePrUrlParts(url)?.number
    const name = draft ? 'draft PR' : 'PR'
    return number ? `Review ${name} #${number}` : `Review ${name}`
}

function pickedUpOn(date: string | null | undefined): string {
    return date ? ` on ${shortDate(date)}` : ''
}

function claimant(assignee: NonNullable<SignalReport['assignee']>): string {
    const name = assignee.user ? fullName(assignee.user) || assignee.user.email : null
    return name ?? assignee.agent ?? 'An agent'
}

function namedPullRequestReview({ namedPullRequest }: TodayNextStepContext): TodayPrimaryAction | null {
    return namedPullRequest
        ? { kind: 'review', url: namedPullRequest.url, label: `View PR #${namedPullRequest.number}` }
        : null
}

function alreadyAddressed(context: TodayNextStepContext): TodayNextStep {
    const review = namedPullRequestReview(context)
    if (review) {
        return { primary: review, note: null, taskPickedUp: false }
    }
    return {
        primary: null,
        note: context.solutionNamesPullRequest ? null : 'A fix is already in flight. The full report links to it.',
        taskPickedUp: false,
    }
}

function pullRequestStep(report: SignalReport): TodayNextStep | null {
    const pullRequest = primaryReportPullRequest(report)
    const url = safeHttpUrl(pullRequest.url ?? '')
    if (!url) {
        return null
    }
    if (pullRequest.merged) {
        return { primary: null, note: 'The fix is merged. Resolve the report once it is live.', taskPickedUp: false }
    }
    if (pullRequest.state === 'closed') {
        return null
    }
    return {
        primary: { kind: 'review', url, label: reviewLabel(url, pullRequest.state === 'draft') },
        note: REVIEW_NOTES[pullRequest.review_decision ?? ''] ?? null,
        taskPickedUp: false,
    }
}

function pickedUpStep(report: SignalReport, context: TodayNextStepContext): TodayNextStep | null {
    const assignee = report.assignee ?? null
    const taskPickedUp = context.slotClaimed || assignee?.kind === 'task'
    if (taskPickedUp && context.runningTask) {
        const primary = { kind: 'open_task' as const, label: 'Open the running task', ...context.runningTask }
        return { primary, note: null, taskPickedUp: true }
    }
    if (taskPickedUp) {
        return {
            primary: namedPullRequestReview(context) ?? START,
            note: `A PostHog task picked this up${pickedUpOn(assignee?.claimed_at)}.`,
            taskPickedUp: true,
        }
    }
    if (assignee?.kind === 'user' || assignee?.kind === 'agent') {
        return {
            primary: namedPullRequestReview(context) ?? START,
            note: `${claimant(assignee)} picked this up${pickedUpOn(assignee.claimed_at)}.`,
            taskPickedUp: false,
        }
    }
    return null
}

export function todayNextStep(report: SignalReport, context: TodayNextStepContext): TodayNextStep {
    const step = pullRequestStep(report) ?? pickedUpStep(report, context)
    if (step) {
        return step
    }
    if (report.already_addressed) {
        return alreadyAddressed(context)
    }
    return { primary: START, note: null, taskPickedUp: false }
}

type TodayWorkKind = 'implement' | 'investigate'

export function reportWorkKind(report: Pick<SignalReport, 'actionability' | 'status'>): TodayWorkKind {
    return report.actionability === 'immediately_actionable' && report.status !== 'pending_input'
        ? 'implement'
        : 'investigate'
}

function buildReportInvestigationPrompt(report: Pick<SignalReport, 'id'>, reportUrl: string): string {
    return `Investigate the PostHog Inbox report at ${reportUrl} (report ID: ${report.id}).

Use the PostHog MCP tools to read the report and its full work log with inbox-report-artefacts-list. Confirm the problem it describes against the current code and data, and find the root cause.

Reply with what you found: whether the problem is real, what causes it, how many people it affects, and the smallest fix you would make. Do not change code, open a pull request, or change the report's state.`
}

export function resolveDisabledReason(report: SignalReport, sampleReason: string | null): string | null {
    if (sampleReason) {
        return sampleReason
    }
    return canResolveReport(report) ? null : 'You can resolve a report only after the agent finishes its research.'
}

export interface TodayKickoffReasons {
    createPrDisabledReason: string | null
    aiConsentDisabledReason: string | null
}

export function startDisabledReason(
    report: SignalReport,
    taskPickedUp: boolean,
    { createPrDisabledReason, aiConsentDisabledReason }: TodayKickoffReasons
): string | null {
    if (taskPickedUp) {
        return 'A task already picked this up.'
    }
    if (!isActionCapableReport(report)) {
        return 'This report can’t start work. Ask about it instead.'
    }
    return reportWorkKind(report) === 'implement' ? createPrDisabledReason : aiConsentDisabledReason
}

export function reportWorkPrompt(report: SignalReport, reportUrl: string): string {
    if (reportWorkKind(report) === 'implement') {
        return buildReportImplementationPrompt(report, reportUrl)
    }
    return buildReportInvestigationPrompt(report, reportUrl)
}
