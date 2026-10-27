import { dayjs } from 'lib/dayjs'

export function metricPeriod(dates: string[]): string {
    const first = dayjs(dates[0])
    const last = dayjs(dates.at(-1))
    if (!dates.length || !first.isValid() || !last.isValid()) {
        return ''
    }
    const format = first.isSame(last, 'year') ? 'MMM D' : 'MMM D, YYYY'
    return first.isSame(last, 'day') ? last.format(format) : `${first.format(format)}–${last.format(format)}`
}

export function money(cents: number): string {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: cents % 100 ? 2 : 0,
    }).format(cents / 100)
}

export function number(value: number | null | undefined, unit = ''): string {
    if (value == null) {
        return '—'
    }
    return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value)}${unit === '%' ? '%' : unit ? ` ${unit}` : ''}`
}

export function errorMessage(error: unknown): string {
    if (error instanceof Error) {
        return error.message
    }
    if (typeof error === 'object' && error !== null && 'detail' in error) {
        return String(error.detail)
    }
    return 'Something went wrong. Please try again.'
}

export function compactMoney(cents: number): string {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        notation: 'compact',
        maximumFractionDigits: cents < 100000 ? 0 : 1,
    }).format(cents / 100)
}

export function progressPercent(progress: number): string {
    return `${Math.round(progress * 100)}%`
}
