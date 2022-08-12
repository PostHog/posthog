import React from 'react'
import { LemonSelectOptions } from '@posthog/lemon-ui'
import { range } from 'lib/utils'
import { urls } from 'scenes/urls'
import { InsightShortId, SlackChannelType } from '~/types'
import { IconMail, IconSlack, IconSlackExternal } from '../icons'
import { LemonSelectMultipleOptionItem } from '../LemonSelectMultiple/LemonSelectMultiple'

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

export const targetTypeOptions: LemonSelectOptions<'email' | 'slack'> = [
    { key: 'email', label: 'Email', icon: <IconMail /> },
    { key: 'slack', label: 'Slack', icon: <IconSlack /> },
    // { key: 'webhook', label: 'Webhook', icon: <IconOpenInNew /> },
]

export const intervalOptions: LemonSelectOptions<number> = range(1, 13).map((x) => ({ key: x, label: x.toString() }))

export const frequencyOptions: LemonSelectOptions<'daily' | 'weekly' | 'monthly'> = [
    { key: 'daily', label: 'days' },
    { key: 'weekly', label: 'weeks' },
    { key: 'monthly', label: 'months' },
]

export const weekdayOptions: LemonSelectOptions<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday'
> = [
    { key: 'monday', label: 'Monday' },
    { key: 'tuesday', label: 'Tuesday' },
    { key: 'wednesday', label: 'Wednesday' },
    { key: 'thursday', label: 'Thursday' },
    { key: 'friday', label: 'Friday' },
    { key: 'saturday', label: 'Saturday' },
    { key: 'sunday', label: 'Sunday' },
]

export const monthlyWeekdayOptions: LemonSelectOptions<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday' | 'day'
> = [...weekdayOptions, { key: 'day', label: 'day' }]

export const bysetposOptions: LemonSelectOptions<'1' | '2' | '3' | '4' | '-1'> = [
    { key: '1', label: 'first' },
    { key: '2', label: 'second' },
    { key: '3', label: 'third' },
    { key: '4', label: 'fourth' },
    { key: '-1', label: 'last' },
]

export const timeOptions: LemonSelectOptions<string> = range(0, 24).map((x) => ({
    key: String(x),
    label: `${String(x).padStart(2, '0')}:00`,
}))

export const getSlackChannelOptions = (
    value: string,
    slackChannels?: SlackChannelType[] | null
): LemonSelectMultipleOptionItem[] => {
    return slackChannels
        ? slackChannels.map((x) => ({
              key: `${x.id}|#${x.name}`,
              labelComponent: (
                  <span className="flex items-center">
                      {x.is_private ? `🔒${x.name}` : `#${x.name}`}
                      {x.is_ext_shared ? <IconSlackExternal className="ml-2" /> : null}
                  </span>
              ),
              label: `${x.id} #${x.name}`,
          }))
        : value
        ? [
              {
                  key: value,
                  label: value?.split('|')?.pop() || value,
              },
          ]
        : []
}
