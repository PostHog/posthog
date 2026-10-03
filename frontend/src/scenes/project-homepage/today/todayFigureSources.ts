import { Dayjs, dayjs } from 'lib/dayjs'
import { isNotNil } from 'lib/utils/guards'

import type { FigureMarkApi, FigureQuoteApi, SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { inlineSegments, shortDate } from './todayProse'

export interface TodayTextSpan {
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
          link: { url: string; label: string } | null
      }
    | { kind: 'none' }

export interface TodayMarkedFigure extends TodayTextSpan {
    segment: number
    text: string
    content: TodayFigureCardContent
}

function quoteContent(quote: FigureQuoteApi, signals: SignalViewApi[]): TodayFigureCardContent | null {
    const quoted = { excerpt: quote.sentence, highlight: { start: quote.start, end: quote.end } }
    if (quote.kind === 'research') {
        return { kind: 'research', at: quote.at, ...quoted }
    }
    const signal = signals.find((candidate) => candidate.signal_id === quote.signal_id)
    return signal ? { kind: 'signal', signal, ...quoted } : null
}

export function markedFigures(markdown: string, marks: FigureMarkApi[], signals: SignalViewApi[]): TodayMarkedFigure[] {
    let offset = 0
    const segments = inlineSegments(markdown).map((segment) => {
        const start = offset
        offset += segment.text.length
        return { ...segment, start }
    })
    return marks.flatMap((mark) => {
        const segment = segments.findIndex(
            (candidate) =>
                candidate.kind === 'text' &&
                candidate.start <= mark.start &&
                mark.end <= candidate.start + candidate.text.length
        )
        const content = quoteContent(mark.quote, signals)
        if (segment < 0 || !content) {
            return []
        }
        const start = mark.start - segments[segment].start
        const end = mark.end - segments[segment].start
        const placed = segments[segment].text.slice(start, end) === mark.figure
        return placed ? [{ segment, start, end, text: mark.figure, content }] : []
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
