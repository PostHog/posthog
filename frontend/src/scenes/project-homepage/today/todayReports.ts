import { dayjs } from 'lib/dayjs'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayBriefingSegment, TodayEvidence, TodayEvidenceKind, TodayStory, TodayStoryIcon } from './todayTypes'

interface SourceStyle {
    label: string
    color: string
    kind: TodayEvidenceKind
    icon: TodayStoryIcon
}

const SOURCE_STYLES: Record<string, SourceStyle> = {
    error_tracking: { label: 'Error tracking', color: '#e58e00', kind: 'error', icon: 'error' },
    sentry: { label: 'Sentry', color: '#e58e00', kind: 'error', icon: 'error' },
    session_replay: { label: 'Session replay', color: '#0457ff', kind: 'replay', icon: 'replay' },
    replay_vision: { label: 'Replay vision', color: '#0457ff', kind: 'replay', icon: 'replay' },
    llm_analytics: { label: 'LLM analytics', color: '#a737d2', kind: 'trace', icon: 'llm' },
    analytics: { label: 'Product analytics', color: '#2f80fa', kind: 'analytics', icon: 'analytics' },
    github: { label: 'GitHub', color: '#ff5c1c', kind: 'code', icon: 'pr' },
    gitlab: { label: 'GitLab', color: '#ff5c1c', kind: 'code', icon: 'pr' },
    linear: { label: 'Linear', color: '#6d4fff', kind: 'code', icon: 'inbox' },
    jira: { label: 'Jira', color: '#2f80fa', kind: 'code', icon: 'inbox' },
    conversations: { label: 'Support', color: '#6d4fff', kind: 'survey', icon: 'survey' },
    zendesk: { label: 'Zendesk', color: '#6d4fff', kind: 'survey', icon: 'survey' },
    logs: { label: 'Logs', color: '#5c5c57', kind: 'trace', icon: 'trace' },
    pganalyze: { label: 'pganalyze', color: '#5c5c57', kind: 'warehouse', icon: 'analytics' },
}

const FALLBACK_STYLE: SourceStyle = { label: 'Self-driving', color: '#5c5c57', kind: 'analytics', icon: 'inbox' }

function sourceStyle(source: string | undefined): SourceStyle {
    return (source && SOURCE_STYLES[source]) || FALLBACK_STYLE
}

function sourceLabel(source: string): string {
    return SOURCE_STYLES[source]?.label ?? source.replace(/_/g, ' ').replace(/^./, (first) => first.toUpperCase())
}

/** The report summary as plain paragraphs: markdown links become their text and headings lose their markers. */
export function summaryParagraphs(summary: string | null): string[] {
    if (!summary) {
        return []
    }
    return summary
        .split(/\n{2,}/)
        .map((paragraph) =>
            paragraph
                .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
                .replace(/^#+\s*/gm, '')
                .replace(/[*_`]/g, '')
                .replace(/\s+/g, ' ')
                .trim()
        )
        .filter(Boolean)
        .slice(0, 3)
}

export function reportToStory(report: SignalReport, reportHref: string): TodayStory {
    const sources = report.source_products ?? []
    const style = sourceStyle(sources[0])
    const title = report.title?.trim() || 'Untitled report'
    const paragraphs = summaryParagraphs(report.summary)
    const pullRequestUrl = report.implementation_pr_url ?? undefined
    const evidence: TodayEvidence[] = sources.slice(0, 4).map((source) => {
        const { color, kind } = sourceStyle(source)
        return {
            product: sourceLabel(source),
            value: `${report.signal_count} ${report.signal_count === 1 ? 'signal' : 'signals'}`,
            detail: `Part of the evidence behind this report.`,
            color,
            kind,
        }
    })

    return {
        id: `report-${report.id}`,
        title,
        meta: [sources.length ? sourceLabel(sources[0]) : null, dayjs(report.updated_at).fromNow()]
            .filter(Boolean)
            .join(' · '),
        color: style.color,
        icon: pullRequestUrl ? 'pr' : style.icon,
        heading: title,
        paragraphs: paragraphs.length ? paragraphs : ['Open the report to read what Self-driving found.'],
        evidence,
        action: pullRequestUrl
            ? {
                  primary: 'Review the pull request',
                  status: report.implementation_pr_merged ? 'Merged' : 'Pull request ready',
                  tone: 'success',
                  confirmation: 'Opened the pull request.',
                  href: pullRequestUrl,
              }
            : {
                  primary: 'Open the report',
                  status: `${report.signal_count} ${report.signal_count === 1 ? 'signal' : 'signals'}`,
                  tone: report.priority === 'P0' || report.priority === 'P1' ? 'warning' : 'info',
                  confirmation: 'Opened the report.',
                  href: reportHref,
              },
        completed: report.status === 'resolved',
    }
}

/** One linked sentence per story, so every story in the briefing opens from the text. */
export function briefingForStories(stories: TodayStory[]): TodayBriefingSegment[][] {
    const open = stories.filter((story) => !story.completed && !story.secondary)
    if (!open.length) {
        return [[{ text: 'Nothing needs you right now. New reports land here as Self-driving finds them.' }]]
    }
    const [first, ...rest] = open
    const paragraphs: TodayBriefingSegment[][] = [
        [
            { text: first.title, link: first.id, highlight: first.action.href?.includes('/pull/') ?? false },
            { text: '.' },
        ],
    ]
    if (rest.length) {
        const shown = rest.slice(0, 3)
        paragraphs.push([
            { text: 'Keep an eye on ' },
            ...shown.flatMap((story, index): TodayBriefingSegment[] => [
                { text: story.title.charAt(0).toLowerCase() + story.title.slice(1), link: story.id },
                { text: index === shown.length - 1 ? '.' : index === shown.length - 2 ? ', and ' : ', ' },
            ]),
        ])
    }
    return paragraphs
}
