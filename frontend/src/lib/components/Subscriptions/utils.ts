import { LemonSelectOptions } from '@posthog/lemon-ui'
import { pluralize, range } from 'lib/utils'
import { urls } from 'scenes/urls'
import { InsightShortId, SubscriptionType } from '~/types'

export interface SubscriptionBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

export const urlForSubscriptions = ({ dashboardId, insightShortId }: SubscriptionBaseProps): string => {
    if (insightShortId) {
        return urls.insightSubcriptions(insightShortId)
    } else if (dashboardId) {
        return urls.dashboardSubcriptions(dashboardId)
    }
    return ''
}

export const urlForSubscription = (
    id: number | 'new',
    { dashboardId, insightShortId }: SubscriptionBaseProps
): string => {
    if (insightShortId) {
        return urls.insightSubcription(insightShortId, id.toString())
    } else if (dashboardId) {
        return urls.dashboardSubcription(dashboardId, id.toString())
    }
    return ''
}

export const intervalOptions: LemonSelectOptions = range(1, 13).reduce(
    (acc, x) => ({
        ...acc,
        [x]: { label: x },
    }),
    {}
)

export const frequencyOptions: LemonSelectOptions = {
    daily: { label: 'days' },
    weekly: { label: 'weeks' },
    monthly: { label: 'months' },
}

export const weekdayOptions: LemonSelectOptions = {
    monday: { label: 'monday' },
    tuesday: { label: 'tuesday' },
    wednesday: { label: 'wednesday' },
    thursday: { label: 'thursday' },
    friday: { label: 'friday' },
    saturday: { label: 'saturday' },
    sunday: { label: 'sunday' },
}

export const monthlyWeekdayOptions: LemonSelectOptions = {
    day: { label: 'day' },
    ...weekdayOptions,
}

export const bysetposOptions: LemonSelectOptions = {
    '1': { label: 'first' },
    '2': { label: 'second' },
    '3': { label: 'third' },
    '4': { label: 'fourth' },
    '-1': { label: 'last' },
}

export const timeOptions: LemonSelectOptions = range(0, 24).reduce(
    (acc, x) => ({
        ...acc,
        [String(x)]: { label: `${String(x).padStart(2, '0')}:00` },
    }),
    {}
)

const humanFrequencyMap: { [key in SubscriptionType['frequency']]: string } = {
    daily: 'day',
    weekly: 'week',
    monthly: 'month',
    yearly: 'year',
}

export function summarizeSubscription(subscription: SubscriptionType): string {
    const frequency = pluralize(subscription.interval, humanFrequencyMap[subscription.frequency], undefined, false)
    let summary = `Sent every ${subscription.interval > 1 ? subscription.interval + ' ' : ''}${frequency}`

    if (subscription.byweekday?.length && subscription.bysetpos) {
        summary += ` on the ${bysetposOptions[subscription.bysetpos]?.label} ${
            subscription.byweekday.length === 1 ? subscription.byweekday[0] : 'day'
        }`
    }

    return summary
}
