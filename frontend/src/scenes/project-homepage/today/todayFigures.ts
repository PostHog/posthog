import type { TodayQuotedText } from './todayFigureSources'

const MONTH_AFTER = /^\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/

export interface TodayQuoteSegment {
    text: string
    marked: boolean
}

function withoutDigitCommas(text: string): string {
    return text.replace(/(\d),(?=\d{3}\b)/g, '$1')
}

function numberBody(value: string): string {
    const [whole, fraction] = withoutDigitCommas(value).split('.')
    return whole.split('').join(',?') + (fraction ? `\\.${fraction}` : '')
}

function numberPattern(value: string): RegExp {
    return new RegExp(`(?<![\\d.,/:-])${numberBody(value)}(?![\\d/:-]|[.,]\\d)`)
}

function firstMatch(text: string, value: string): { start: number; end: number } | null {
    const pattern = new RegExp(
        `(?:[$€£])?${numberPattern(value).source}(?:\\s?(?:ms|K|M)\\b|%|\\s(?:seconds?|minutes?|hours?)\\b)?`,
        'g'
    )
    for (let match = pattern.exec(text); match; match = pattern.exec(text)) {
        const end = match.index + match[0].length
        if (!MONTH_AFTER.test(text.slice(end))) {
            return { start: match.index, end }
        }
    }
    return null
}

export function highlightSegments(text: string, values: string[]): TodayQuoteSegment[] {
    const matches = values
        .map((value) => firstMatch(text, value))
        .filter((match): match is { start: number; end: number } => match !== null)
        .sort((first, second) => first.start - second.start)
    const segments: TodayQuoteSegment[] = []
    let last = 0
    for (const match of matches) {
        if (match.start < last) {
            continue
        }
        if (match.start > last) {
            segments.push({ text: text.slice(last, match.start), marked: false })
        }
        segments.push({ text: text.slice(match.start, match.end), marked: true })
        last = match.end
    }
    if (last < text.length) {
        segments.push({ text: text.slice(last), marked: false })
    }
    return segments
}

export function quoteSegments(quote: TodayQuotedText, figure: string): TodayQuoteSegment[] {
    const { excerpt, highlight } = quote
    if (!highlight) {
        return highlightSegments(excerpt, quote.values ?? [figure])
    }
    return [
        { text: excerpt.slice(0, highlight.start), marked: false },
        { text: excerpt.slice(highlight.start, highlight.end), marked: true },
        { text: excerpt.slice(highlight.end), marked: false },
    ].filter((segment) => segment.text)
}
