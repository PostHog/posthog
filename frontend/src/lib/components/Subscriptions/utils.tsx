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

export const targetTypeOptions: LemonSelectOptions = {
    email: { label: 'Email', icon: <IconMail /> },
    slack: { label: 'Slack', icon: <IconSlack /> },
    // webhook: { label: 'Webhook', icon: <IconOpenInNew /> },
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
    monday: { label: 'Monday' },
    tuesday: { label: 'Tuesday' },
    wednesday: { label: 'Wednesday' },
    thursday: { label: 'Thursday' },
    friday: { label: 'Friday' },
    saturday: { label: 'Saturday' },
    sunday: { label: 'Sunday' },
}

export const monthlyWeekdayOptions = [
    {
        options: weekdayOptions,
    },
    {
        options: {
            day: { label: 'day' },
        },
    },
]

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
                      {x.is_ext_shared ? <IconSlackExternal className="ml-05" /> : null}
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
