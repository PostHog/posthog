import { fullName } from 'lib/utils/strings'

import { buildReportImplementationPrompt } from 'products/signals/frontend/inbox/components/detail/buildReportImplementationPrompt'
import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import type { SignalReport } from 'products/signals/frontend/inbox/types'
import { canResolveReport } from 'products/signals/frontend/inbox/utils/reportActions'
import { parsePrUrlParts, safeHttpUrl } from 'products/signals/frontend/inbox/utils/reportPresentation'
import { primaryReportPullRequest } from 'products/signals/frontend/inbox/utils/reportPullRequests'

import { shortDate } from './todayProse'

export type TodayPrimaryAction =
    | { kind: 'review'; url: string; label: string }
    | { kind: 'open_task'; label: string; taskId: string; runId: string }
    | { kind: 'start' }

interface TodayNextStep {
    primary: TodayPrimaryAction | null
    note: string | null
    pickedUp: boolean
}

interface TodayNextStepContext {
    solution: string | null
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

function inFlightReview(
    report: Pick<SignalReport, 'summary' | 'repo_slug'>,
    solution: string | null
): TodayPrimaryAction | null {
    const pullRequest = inFlightPullRequest(report, solution)
    return pullRequest ? { kind: 'review', url: pullRequest.url, label: `View PR #${pullRequest.number}` } : null
}

function alreadyAddressed(report: SignalReport, solution: string | null): TodayNextStep {
    const review = inFlightReview(report, solution)
    if (review) {
        return { primary: review, note: null, pickedUp: false }
    }
    const solutionNamesFix = pullRequestsIn(solution, report.repo_slug).size > 0
    return {
        primary: null,
        note: solutionNamesFix ? null : 'A fix is already in flight. The full report links to it.',
        pickedUp: false,
    }
}

export function todayNextStep(report: SignalReport, context: TodayNextStepContext): TodayNextStep {
    const pullRequest = primaryReportPullRequest(report)
    const url = safeHttpUrl(pullRequest.url ?? '')
    if (url && pullRequest.merged) {
        return { primary: null, note: 'The fix is merged. Resolve the report once it is live.', pickedUp: false }
    }
    if (url && pullRequest.state !== 'closed') {
        return {
            primary: { kind: 'review', url, label: reviewLabel(url, pullRequest.state === 'draft') },
            note: REVIEW_NOTES[pullRequest.review_decision ?? ''] ?? null,
            pickedUp: false,
        }
    }
    const assignee = report.assignee ?? null
    if (context.slotClaimed || assignee?.kind === 'task') {
        if (context.runningTask) {
            const primary = { kind: 'open_task' as const, label: 'Open the running task', ...context.runningTask }
            return { primary, note: null, pickedUp: true }
        }
        return {
            primary: inFlightReview(report, context.solution) ?? START,
            note: `A PostHog task picked this up${pickedUpOn(assignee?.claimed_at)}.`,
            pickedUp: true,
        }
    }
    if (assignee?.kind === 'user' || assignee?.kind === 'agent') {
        return {
            primary: inFlightReview(report, context.solution) ?? START,
            note: `${claimant(assignee)} picked this up${pickedUpOn(assignee.claimed_at)}.`,
            pickedUp: true,
        }
    }
    if (report.already_addressed) {
        return alreadyAddressed(report, context.solution)
    }
    return { primary: START, note: null, pickedUp: false }
}

const GITHUB_PULL_URL = /https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/(\d+)/g

const BARE_PULL_REFERENCE = /\bPR #(\d+)\b/g

function pullRequestsIn(text: string | null | undefined, repoSlug?: string | null): Map<string, string> {
    const pulls = new Map([...(text ?? '').matchAll(GITHUB_PULL_URL)].map((match) => [match[1], match[0]]))
    if (pulls.size === 0 && repoSlug) {
        for (const match of (text ?? '').matchAll(BARE_PULL_REFERENCE)) {
            pulls.set(match[1], `https://github.com/${repoSlug}/pull/${match[1]}`)
        }
    }
    return pulls
}

function onlyPullRequest(
    text: string | null | undefined,
    repoSlug?: string | null
): { url: string; number: string } | null {
    const pulls = pullRequestsIn(text, repoSlug)
    if (pulls.size !== 1) {
        return null
    }
    const [[number, url]] = [...pulls.entries()]
    return { url, number }
}

export function inFlightPullRequest(
    report: Pick<SignalReport, 'summary' | 'repo_slug'>,
    solution: string | null
): { url: string; number: string } | null {
    return onlyPullRequest(solution, report.repo_slug) ?? onlyPullRequest(report.summary, report.repo_slug)
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

export function startDisabledReason(
    report: SignalReport,
    pickedUp: boolean,
    createPrDisabledReason: string | null
): string | null {
    if (pickedUp) {
        return 'A task already picked this up.'
    }
    if (!isActionCapableReport(report)) {
        return 'This report can’t start work. Ask about it instead.'
    }
    return createPrDisabledReason
}

export function reportWorkPrompt(report: SignalReport, reportUrl: string): string {
    if (reportWorkKind(report) === 'implement') {
        return buildReportImplementationPrompt(report, reportUrl)
    }
    return buildReportInvestigationPrompt(report, reportUrl)
}
