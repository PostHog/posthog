import { IconLetter } from '@posthog/icons'
import { LemonSelectOptions } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { range } from 'lib/utils'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

export interface SubscriptionBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

export const urlForSubscriptions = ({ dashboardId, insightShortId }: SubscriptionBaseProps): string => {
    if (insightShortId) {
        return urls.insightSubcriptions(insightShortId)
    } else if (dashboardId) {
        return urls.dashboardSubscriptions(dashboardId)
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
        return urls.dashboardSubscription(dashboardId, id.toString())
    }
    return ''
}

export const targetTypeOptions: LemonSelectOptions<'email' | 'slack'> = [
    { value: 'email', label: 'Email', icon: <IconLetter /> },
    { value: 'slack', label: 'Slack', icon: <IconSlack /> },
    // { value: 'webhook', label: 'Webhook', icon: <IconOpenInNew /> },
]

export const intervalOptions: LemonSelectOptions<number> = range(1, 13).map((x) => ({ value: x, label: x.toString() }))

export const frequencyOptionsSingular: LemonSelectOptions<'daily' | 'weekly' | 'monthly'> = [
    { value: 'daily', label: 'day' },
    { value: 'weekly', label: 'week' },
    { value: 'monthly', label: 'month' },
]
export const frequencyOptionsPlural: LemonSelectOptions<'daily' | 'weekly' | 'monthly'> = [
    { value: 'daily', label: 'days' },
    { value: 'weekly', label: 'weeks' },
    { value: 'monthly', label: 'months' },
]

export const weekdayOptions: LemonSelectOptions<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday'
> = [
    { value: 'monday', label: 'Monday' },
    { value: 'tuesday', label: 'Tuesday' },
    { value: 'wednesday', label: 'Wednesday' },
    { value: 'thursday', label: 'Thursday' },
    { value: 'friday', label: 'Friday' },
    { value: 'saturday', label: 'Saturday' },
    { value: 'sunday', label: 'Sunday' },
]

export const monthlyWeekdayOptions: LemonSelectOptions<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday' | 'day'
> = [...weekdayOptions, { value: 'day', label: 'day' }]

export const bysetposOptions: LemonSelectOptions<'1' | '2' | '3' | '4' | '-1'> = [
    { value: '1', label: 'first' },
    { value: '2', label: 'second' },
    { value: '3', label: 'third' },
    { value: '4', label: 'fourth' },
    { value: '-1', label: 'last' },
]

export const timeOptions: LemonSelectOptions<string> = range(0, 24).map((x) => ({
    value: String(x),
    label: `${String(x).padStart(2, '0')}:00`,
}))
