import { dayjs } from 'lib/dayjs'

export const MODELS_USAGE_RANGE_DAYS = [7, 30, 90]

export function modelsUsageRangeLabel(days: number): string {
    return `Last ${days} complete days`
}

export function modelsUsageRelativeDateFrom(days: number): string {
    return `-${days}d`
}

export function modelsUsageRangeDescription(days: number, today: dayjs.Dayjs): string {
    return `${today.subtract(days, 'day').format('MMM D, YYYY')} – ${today.subtract(1, 'day').format('MMM D, YYYY')}`
}

export function lastCompleteUsageDay(): Date {
    const lastCompleteUtcDay = dayjs.utc().startOf('day').subtract(1, 'day')
    return new Date(lastCompleteUtcDay.year(), lastCompleteUtcDay.month(), lastCompleteUtcDay.date())
}
