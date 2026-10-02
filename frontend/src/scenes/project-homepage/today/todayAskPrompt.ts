import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { BriefingApi } from 'products/today/frontend/generated/api.schemas'

import { isExternalHref, itemHref } from './todayBriefingItems'

export const WALK_THROUGH_QUESTION = 'Walk me through my Today briefing and tell me what to do first.'

/** What the Today page showed when the person asked, so PostHog AI can read the same briefing and reports. */
export type TodayAskContext =
    | { kind: 'briefing'; briefing: BriefingApi }
    | { kind: 'reports'; reports: SignalReport[] }
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

/**
 * The question with the Today page's context under it, as Markdown. PostHog AI reads the briefing and reports
 * through the MCP tools the context names, so the context holds ids rather than the full report text.
 */
export function todayAskPrompt(question: string, context: TodayAskContext): string {
    if (context.kind === 'none' || (context.kind === 'reports' && context.reports.length === 0)) {
        return question
    }
    return [
        question,
        '',
        '---',
        '',
        `#### Context from my ${markdownLink('Today home page', urls.projectHomepage())}`,
        '',
        ...(context.kind === 'briefing' ? briefingContext(context.briefing) : reportsContext(context.reports)),
    ].join('\n')
}
