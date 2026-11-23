import { dayjs } from 'lib/dayjs'

/**
 * Pick an hour-vs-day bucket interval for a chart series based on the
 * date-from string. Shared by the tagger list and detail charts so they
 * bucket identically.
 */
export function getIntervalFromDateRange(dateFrom: string | null): 'hour' | 'day' {
    if (!dateFrom) {
        return 'day'
    }
    if (dateFrom === 'dStart' || dateFrom === '-0d' || dateFrom === '-0dStart') {
        return 'hour'
    }
    const match = dateFrom.match(/^-(\d+)([hdwmy])/i)
    if (match) {
        const value = parseInt(match[1])
        const unit = match[2].toLowerCase()
        const hoursMap: Record<string, number> = { h: 1, d: 24, w: 168, m: 720, y: 8760 }
        const hours = value * (hoursMap[unit] || 24)
        return hours <= 24 ? 'hour' : 'day'
    }
    const duration = dayjs.duration(dayjs().diff(dayjs(dateFrom)))
    return duration.asDays() <= 1 ? 'hour' : 'day'
}
