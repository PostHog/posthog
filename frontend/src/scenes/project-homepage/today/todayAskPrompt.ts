import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { BriefingApi } from 'products/today/frontend/generated/api.schemas'

import { itemReportId } from './todayBriefingItems'

export const WALK_THROUGH_QUESTION = 'Walk me through my Today briefing and tell me what to do first.'

/** What the Today page showed when the person asked, so PostHog AI can read the same briefing and reports. */
export type TodayAskContext =
    | { kind: 'briefing'; briefing: BriefingApi }
    | { kind: 'reports'; reports: SignalReport[] }
    | { kind: 'none' }

function briefingContext(briefing: BriefingApi): string[] {
    const items = briefing.items.map((item) => {
        const reportId = itemReportId(item)
        const ref = reportId ? `report id \`${reportId}\`` : `item \`${item.key}\`, ${item.url}`
        return `${item.rank}. ${item.label} (${item.signal}; ${ref}; state: ${item.state})`
    })
    return [
        `- Briefing id: \`${briefing.id}\`, for ${briefing.local_day}`,
        ...(items.length ? ['- Items, most urgent first:', ...items.map((line) => `  ${line}`)] : []),
        ...(briefing.more_reports_count > 0
            ? [`- ${briefing.more_reports_count} more open reports for me are in the Inbox.`]
            : []),
        '',
        `Use the \`today-briefing-get\` tool to read this briefing and check that its id is \`${briefing.id}\`. ` +
            'If the id is different, a newer briefing replaced it: tell me, and use the newer one. ' +
            'Use `today-candidates-list` for the facts behind each item, and `inbox-reports-retrieve` with a report id ' +
            'to read a report in full before you follow up on it.',
    ]
}

function reportsContext(reports: SignalReport[]): string[] {
    return [
        '- My briefing is not written yet. The page shows these reports, most urgent first:',
        ...reports.map(
            (report, index) =>
                `  ${index + 1}. ${report.title ?? 'Untitled report'} (report id \`${report.id}\`` +
                `${report.priority ? `, ${report.priority}` : ''})`
        ),
        '',
        'Use `inbox-reports-retrieve` with a report id to read a report in full before you follow up on it.',
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
    const homeUrl = urls.absolute(urls.currentProject(urls.projectHomepage()))
    return [
        question,
        '',
        '---',
        '',
        `## Context: my Today home page (${homeUrl})`,
        '',
        ...(context.kind === 'briefing' ? briefingContext(context.briefing) : reportsContext(context.reports)),
    ].join('\n')
}
