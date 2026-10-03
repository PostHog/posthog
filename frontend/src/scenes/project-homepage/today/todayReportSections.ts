import { isActionCapableReport } from 'products/signals/frontend/inbox/inboxTaskKickoffLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { parseReportSummary } from 'products/signals/frontend/inbox/utils/reportSummary'

import { conciseText, paragraphs } from './todayProse'

export interface TodayReportSections {
    lead: string
    impact: string | null
    proposal: string | null
}

const PARAGRAPH_HEADING = /^\*\*([^*\n]+?):?\*\*:?\s*$/
const PROPOSAL_HEADINGS = new Set([
    'solution',
    'the solution',
    'fix',
    'the fix',
    'proposed fix',
    'recommended fix',
    'suggested fix',
    'smallest fix',
    'recommendation',
    'recommendations',
    'recommended action',
    'recommended next step',
    'recommended next steps',
    'next step',
    'next steps',
])
const IMPACT_HEADINGS = new Set(['impact'])
const CHART_REFERENCE = /\[([^\]]+)\]\(chart:[^)]*\)/g
const HEADING_WORD_LIMIT = 6

function withoutChartReferences(markdown: string): string {
    return markdown
        .replace(/(?<=[.!?])\s*\[[^\]]+\]\(chart:[^)]*\)\.?(?=\s*$|\n)/gm, '')
        .replace(CHART_REFERENCE, '$1')
        .trim()
}

function cleanSection(text: string | null): string | null {
    return text?.trim() ? withoutChartReferences(text) || null : null
}

function isParagraphHeading(line: string): string | null {
    const match = line.trim().match(PARAGRAPH_HEADING)
    if (!match) {
        return null
    }
    const heading = match[1].trim()
    if (/[.!?]$/.test(heading) || heading.split(/\s+/).length > HEADING_WORD_LIMIT) {
        return null
    }
    return heading
}

function splitParagraphHeadings(markdown: string): { lead: string; sections: { heading: string; body: string }[] } {
    const sections: { heading: string; lines: string[] }[] = []
    const leadLines: string[] = []
    let current = leadLines
    for (const line of markdown.split('\n')) {
        const heading = isParagraphHeading(line)
        if (heading) {
            const section = { heading, lines: [] }
            sections.push(section)
            current = section.lines
            continue
        }
        current.push(line)
    }
    return {
        lead: leadLines.join('\n').trim(),
        sections: sections.map((section) => ({ heading: section.heading, body: section.lines.join('\n').trim() })),
    }
}

export function todayReportSections(summary: string | null | undefined): TodayReportSections {
    const parsed = parseReportSummary(summary)
    if (parsed.sections.length > 0) {
        const [lead] = paragraphs(parsed.lead)
        const find = (kind: string): string | null =>
            parsed.sections.find((section) => section.kind === kind)?.body ?? null
        return {
            lead: withoutChartReferences(lead ?? ''),
            impact: cleanSection(find('impact')),
            proposal: cleanSection(find('solution')),
        }
    }
    const split = splitParagraphHeadings(parsed.lead)
    const [lead] = paragraphs(split.lead)
    const pick = (names: Set<string>): string | null =>
        split.sections.find((section) => names.has(section.heading.toLowerCase()) && section.body)?.body ?? null
    return {
        lead: withoutChartReferences(lead ?? ''),
        impact: cleanSection(pick(IMPACT_HEADINGS)),
        proposal: cleanSection(pick(PROPOSAL_HEADINGS)),
    }
}

const CODE_PATH = /`[^`]*[/.][^`]*`/

function mentionsCodePath(markdown: string): boolean {
    return CODE_PATH.test(markdown)
}

const PROPOSAL_CHARS = 260

export function reportProposal(report: SignalReport, sections: Pick<TodayReportSections, 'proposal'>): string {
    return conciseText(
        sections.proposal ?? (isActionCapableReport(report) ? report.suggested_prompts?.[0] : null),
        PROPOSAL_CHARS
    )
}

const IMPACT_CHARS = 180

export function impactSentence(sections: Pick<TodayReportSections, 'impact'>): string {
    const text = conciseText(sections.impact, IMPACT_CHARS)
    const statesMeasurement = /\d/.test(text) && !mentionsCodePath(text)
    return statesMeasurement ? text : ''
}
