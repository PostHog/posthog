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

export function highlightSegments(text: string, values: string[]): TodayQuoteSegment[] {
    const segments: TodayQuoteSegment[] = []
    let last = 0
    for (const value of values) {
        const pattern = new RegExp(
            `(?:[$€£])?${numberPattern(value).source}(?:\\s?(?:ms|K|M)\\b|%|\\s(?:seconds?|minutes?|hours?)\\b)?`,
            'g'
        )
        pattern.lastIndex = last
        let match = pattern.exec(text)
        while (match && MONTH_AFTER.test(text.slice(match.index + match[0].length))) {
            match = pattern.exec(text)
        }
        if (!match) {
            continue
        }
        if (match.index > last) {
            segments.push({ text: text.slice(last, match.index), marked: false })
        }
        segments.push({ text: match[0], marked: true })
        last = match.index + match[0].length
    }
    if (last < text.length) {
        segments.push({ text: text.slice(last), marked: false })
    }
    return segments
}

export function quoteSegments(quote: TodayQuotedText, figure: string): TodayQuoteSegment[] {
    return highlightSegments(quote.excerpt, quote.values ?? [figure])
}
