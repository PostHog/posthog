export interface TodayFigure {
    start: number
    end: number
    text: string
    value: string
    noun: string | null
}

const FIGURE =
    /(?<![\w.,\-/:#$@→])(?:[$€£])?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?[–-]\s?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?))?(?:%|\s?(?:ms|K|M)\b)?(?![\w:/→]|[.,]\d)/g
const YEAR = /^(19|20)\d{2}$/
const MONTH_AFTER = /^\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/
const TIME_UNIT = /^(?:hours?|days?|weeks?|months?|years?)$/i
const DURATION_UNIT = /^(?:seconds?|minutes?|hours?|days?|weeks?|months?)$/i
const WINDOW_LEAD = /\b(?:trailing|last|past|previous|next|over|within|in)(?:\s+the)?\s+$/i
export const UNIT = /(%|ms|K|M)$/
const CURRENCY = /^[$€£]/

function isTimeWindow(figure: TodayFigure, text: string): boolean {
    return !!figure.noun && TIME_UNIT.test(figure.noun) && WINDOW_LEAD.test(text.slice(0, figure.start))
}

export function findFigures(text: string): TodayFigure[] {
    return numbersIn(text)
        .filter((figure) => figure.noun || UNIT.test(figure.text) || CURRENCY.test(figure.text))
        .filter((figure) => !isTimeWindow(figure, text))
}

export function numbersIn(text: string): TodayFigure[] {
    return [...text.matchAll(FIGURE)]
        .filter((match) => !YEAR.test(match[1]) && !/^0\d/.test(match[1]))
        .filter((match) => !MONTH_AFTER.test(text.slice((match.index ?? 0) + match[0].length)))
        .map((match) => {
            const start = match.index ?? 0
            const numberEnd = start + match[0].length
            const noun = text.slice(numberEnd).match(/^\s+['"‘“]?([A-Za-z][A-Za-z-]*)/)?.[1] ?? null
            const unit = noun && DURATION_UNIT.test(noun) ? text.slice(numberEnd).match(/^\s+[A-Za-z]+/)?.[0] : null
            const end = numberEnd + (unit?.length ?? 0)
            return { start, end, text: text.slice(start, end), value: match[1], noun }
        })
}

const AUDIENCE_NOUN =
    /^(?:people|persons?|users?|teams?|customers?|organi[sz]ations?|orgs?|accounts?|companies|company|projects?|workspaces?|sessions?|visitors?|members?)$/i

export function figuresToMark<T extends Pick<TodayFigure, 'noun'>>(figures: T[], limit: number): Set<T> {
    const ranked = figures
        .map((figure, index) => ({ figure, index, audience: figure.noun && AUDIENCE_NOUN.test(figure.noun) ? 0 : 1 }))
        .sort((first, second) => first.audience - second.audience || first.index - second.index)
    return new Set(ranked.slice(0, limit).map(({ figure }) => figure))
}

const SCALES: Record<string, number> = { K: 1_000, M: 1_000_000 }

export function parseAmount(text: string): number {
    return Number(text.replace(/,/g, ''))
}

export function figureAmount(figure: Pick<TodayFigure, 'text' | 'value'>): number {
    return parseAmount(figure.value) * (SCALES[figure.text.slice(-1)] ?? 1)
}

export function withoutDigitCommas(text: string): string {
    return text.replace(/(\d),(?=\d{3}\b)/g, '$1')
}

function numberBody(value: string): string {
    const [whole, fraction] = withoutDigitCommas(value).split('.')
    return whole.split('').join(',?') + (fraction ? `\\.${fraction}` : '')
}

export function numberPattern(value: string): RegExp {
    return new RegExp(`(?<![\\d.,/:-])${numberBody(value)}(?![\\d/:-]|[.,]\\d)`)
}

export function highlightSegments(text: string, values: string[]): { text: string; marked: boolean }[] {
    const segments: { text: string; marked: boolean }[] = []
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
