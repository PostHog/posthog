import { urls } from 'scenes/urls'

import {
    NO_CHECKOUT_INSTRUCTIONS,
    REPORT_DISCUSSION_STATE_INSTRUCTIONS,
} from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

/** What the Today page showed when the person asked, so PostHog AI can read the same reports. */
export type TodayAskContext =
    | { kind: 'reports'; reports: SignalReport[] }
    /** `canAct` comes from the report's current server state. It is false when that state is unknown. */
    | { kind: 'report'; report: SignalReport; canAct: boolean }
    | { kind: 'none' }

function markdownLink(text: string, href: string): string {
    return `[${text.replace(/[[\]]/g, '\\$&')}](${urls.absolute(urls.currentProject(href))})`
}

// `link_source` tells the report page that a PostHog AI answer wrote the link.
function todayReportHref(reportId: string): string {
    return `${urls.todayReport(reportId)}?link_source=today`
}

function reportsContext(reports: SignalReport[]): string[] {
    return [
        '- The page shows these reports, most urgent first:',
        ...reports.map(
            (report, index) =>
                `  ${index + 1}. ${markdownLink(report.title ?? 'Untitled report', todayReportHref(report.id))}` +
                (report.priority ? ` (${report.priority})` : '')
        ),
        '',
        'The last part of each link path is the report id. Use it with `inbox-reports-retrieve` to read the report in full before you ' +
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
        case 'reports':
            return reportsContext(context.reports)
        case 'report':
            return reportContext(context.report, context.canAct)
    }
}

/**
 * The question with the Today page's context under it, as Markdown. PostHog AI reads the reports
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
