import { urls } from 'scenes/urls'

import {
    NO_CHECKOUT_INSTRUCTIONS,
    REPORT_DISCUSSION_STATE_INSTRUCTIONS,
} from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { BriefingApi } from 'products/today/frontend/generated/api.schemas'

import { isExternalHref, itemHref } from './todayBriefingItems'

export const WALK_THROUGH_QUESTION = 'Walk me through my Today briefing and tell me what to do first.'

/** What the Today page showed when the person asked, so PostHog AI can read the same briefing and reports. */
export type TodayAskContext =
    | { kind: 'briefing'; briefing: BriefingApi }
    | { kind: 'reports'; reports: SignalReport[] }
    /** `canAct` comes from the report's current server state. It is false when that state is unknown. */
    | { kind: 'report'; report: SignalReport; canAct: boolean }
    | { kind: 'none' }

// Briefing item URLs from the API already start with `/project/<id>`, but Today's own report pages do not.
function absoluteHref(href: string): string {
    if (isExternalHref(href)) {
        return href
    }
    return urls.absolute(href.startsWith('/project/') ? href : urls.currentProject(href))
}

function markdownLink(text: string, href: string): string {
    return `[${text.replace(/[[\]]/g, '\\$&')}](${absoluteHref(href)})`
}

function briefingContext(briefing: BriefingApi): string[] {
    const items = briefing.items.map(
        (item) => `${item.rank}. ${markdownLink(item.label, itemHref(item))} (${item.signal}; state: ${item.state})`
    )
    return [
        `- Briefing id: \`${briefing.id}\`, for ${briefing.local_day}`,
        ...(items.length ? ['- Items, most urgent first:', ...items.map((line) => `  ${line}`)] : []),
        ...(briefing.more_reports_count > 0
            ? [
                  `- ${briefing.more_reports_count} more open reports for me are in the ${markdownLink('Inbox', urls.inbox())}.`,
              ]
            : []),
        '',
        `Use the \`today-briefing-get\` tool to read this briefing and check that its id is \`${briefing.id}\`. ` +
            'If the id is different, a newer briefing replaced it: tell me, and use the newer one. ' +
            'Use `today-candidates-list` for the facts behind each item. A report link ends with the report id: use it ' +
            'with `inbox-reports-retrieve` to read the report in full before you follow up on it.',
    ]
}

function reportsContext(reports: SignalReport[]): string[] {
    return [
        '- My briefing is not written yet. The page shows these reports, most urgent first:',
        ...reports.map(
            (report, index) =>
                `  ${index + 1}. ${markdownLink(report.title ?? 'Untitled report', urls.todayReport(report.id))}` +
                (report.priority ? ` (${report.priority})` : '')
        ),
        '',
        'Each link ends with the report id. Use it with `inbox-reports-retrieve` to read the report in full before you ' +
            'follow up on it.',
    ]
}

function reportContext(report: SignalReport, canAct: boolean): string[] {
    return [
        `- Report: ${markdownLink(report.title ?? 'Untitled report', urls.inboxReport('reports', report.id))}`,
        ...(report.priority ? [`- Priority: ${report.priority}`] : []),
        `- Status: ${report.status}`,
        ...(report.implementation_pr_url ? [`- Pull request: ${report.implementation_pr_url}`] : []),
        '',
        'The report link ends with the report id. Use that id with the inbox MCP tools.',
        '',
        // Same split as the Inbox discussion prompt: a report with no work left to do only gets answers.
        ...(canAct
            ? [
                  'If my message is a question, answer it. If it asks for action, carry the action out and summarize ' +
                      'what you did.',
                  '',
                  REPORT_DISCUSSION_STATE_INSTRUCTIONS,
              ]
            : ['Answer my message as a question about this report.']),
        '',
        NO_CHECKOUT_INSTRUCTIONS,
    ]
}

function contextHeading(context: Exclude<TodayAskContext, { kind: 'none' }>): string {
    return context.kind === 'report'
        ? '#### Context from the Inbox report I am reading'
        : `#### Context from my ${markdownLink('Today home page', urls.projectHomepage())}`
}

function contextLines(context: Exclude<TodayAskContext, { kind: 'none' }>): string[] {
    switch (context.kind) {
        case 'briefing':
            return briefingContext(context.briefing)
        case 'reports':
            return reportsContext(context.reports)
        case 'report':
            return reportContext(context.report, context.canAct)
    }
}

/**
 * The question with the Today page's context under it, as Markdown. PostHog AI reads the briefing and reports
 * through the MCP tools the context names, so the context holds ids rather than the full report text.
 *
 * The context goes in a `<posthog_context>` block. The chat hides that block from the person's message
 * (`INJECTED_TAGS` in spaceFeedPreview, and `injectedBlocks` in PostHog Desktop), so the chat shows only the question,
 * but the agent and the run log keep the full prompt.
 */
export function todayAskPrompt(question: string, context: TodayAskContext): string {
    if (context.kind === 'none' || (context.kind === 'reports' && context.reports.length === 0)) {
        return question
    }
    // A literal context tag in a report title would end the block early or fake a trusted block. Same escape as
    // `defang` in posthogContextBlock.
    const body = [contextHeading(context), '', ...contextLines(context)]
        .join('\n')
        .replace(/<(\/?)(posthog_(?:(?:un)?trusted_)?context)/g, '<\\$1$2')
    return [question, '', '<posthog_context>', body, '</posthog_context>'].join('\n')
}
