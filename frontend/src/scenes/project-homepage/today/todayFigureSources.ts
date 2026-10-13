import { Dayjs, dayjs } from 'lib/dayjs'
import { isNotNil } from 'lib/utils/guards'

import type { FigureMarkApi, FigureQuoteApi, SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { inlineSegments, shortDate } from './todayProse'

interface TodayTextSpan {
    start: number
    end: number
}

export interface TodayQuotedText {
    excerpt: string
    values?: string[]
    highlight?: TodayTextSpan
}

export type TodayFigureCardContent =
    | ({
          kind: 'signal'
          signal: SignalViewApi
          working?: { expression: string; result: string }
      } & TodayQuotedText)
    | ({ kind: 'research'; at: string } & TodayQuotedText)
    | {
          kind: 'metric'
          total: string
          at: string | null
          range: { from: string; to: string } | null
          caption: string | null
          window: string | null
          trend: number[] | null
          chartType: 'bar' | 'line'
          link: { url: string; label: string } | null
      }
    | { kind: 'none' }

export interface TodayMarkedFigure extends TodayTextSpan {
    text: string
    content: TodayFigureCardContent
}

function quoteContent(quote: FigureQuoteApi): TodayFigureCardContent | null {
    const quoted = { excerpt: quote.sentence, highlight: { start: quote.start, end: quote.end } }
    if (quote.kind === 'research') {
        return { kind: 'research', at: quote.at, ...quoted }
    }
    return quote.signal ? { kind: 'signal', signal: quote.signal, ...quoted } : null
}

export function markedFigures(markdown: string, marks: FigureMarkApi[]): TodayMarkedFigure[] {
    let offset = 0
    const prose = inlineSegments(markdown).flatMap((segment) => {
        const start = offset
        offset += segment.text.length
        return segment.kind === 'text' ? [{ start, text: segment.text }] : []
    })
    return marks.flatMap((mark) => {
        const segment = prose.find(
            (candidate) => candidate.start <= mark.start && mark.end <= candidate.start + candidate.text.length
        )
        const content = quoteContent(mark.quote)
        const placed =
            segment?.text.slice(mark.start - segment.start, mark.end - segment.start) === mark.figure && content
        return placed ? [{ start: mark.start, end: mark.end, text: mark.figure, content }] : []
    })
}

const STALE_AFTER_DAYS = 7

export function daysAgo(date: string, now: Dayjs = dayjs()): number {
    return now.startOf('day').diff(dayjs(date).startOf('day'), 'day')
}

function sourceDate(content: TodayFigureCardContent): string | null {
    switch (content.kind) {
        case 'research':
            return content.at
        case 'signal':
            return content.signal.timestamp
        default:
            return null
    }
}

export function staleEvidenceDate(figures: TodayMarkedFigure[], now: Dayjs = dayjs()): string | null {
    const newest = figures
        .map((figure) => sourceDate(figure.content))
        .filter(isNotNil)
        .sort()
        .at(-1)
    return newest && daysAgo(newest, now) > STALE_AFTER_DAYS ? newest : null
}

export function anchorToday(text: string, date: string, now: Dayjs = dayjs()): string {
    return daysAgo(date, now) > 0 ? text.replace(/\btoday\b/gi, (word) => `${word} [${shortDate(date)}]`) : text
}
