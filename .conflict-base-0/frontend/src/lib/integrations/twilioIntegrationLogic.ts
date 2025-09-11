import { actions, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { TwilioPhoneNumberType } from '~/types'

import type { twilioIntegrationLogicType } from './twilioIntegrationLogicType'

export const TWILIO_CHANNELS_MIN_REFRESH_INTERVAL_MINUTES = 5

export const twilioIntegrationLogic = kea<twilioIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'twilioIntegrationLogic', key]),
    connect(() => ({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    })),
    actions({
        loadAllTwilioPhoneNumbers: (forceRefresh: boolean = false) => ({ forceRefresh }),
    }),

    loaders(({ props }) => ({
        allTwilioPhoneNumbers: [
            null as { phone_numbers: TwilioPhoneNumberType[]; lastRefreshedAt: string } | null,
            {
                loadAllTwilioPhoneNumbers: async ({ forceRefresh }) => {
                    return await api.integrations.twilioPhoneNumbers(props.id, forceRefresh)
                },
            },
        ],
    })),

    selectors({
        twilioPhoneNumbers: [
            (s) => [s.allTwilioPhoneNumbers],
            (allTwilioPhoneNumbers: { phone_numbers: TwilioPhoneNumberType[]; lastRefreshedAt: string } | null) => {
                return allTwilioPhoneNumbers?.phone_numbers ?? []
            },
        ],
        getPhoneNumberRefreshButtonDisabledReason: [
            (s) => [s.allTwilioPhoneNumbers],
            (allTwilioPhoneNumbers: { phone_numbers: TwilioPhoneNumberType[]; lastRefreshedAt: string } | null) =>
                (): string => {
                    const now = dayjs()
                    if (allTwilioPhoneNumbers) {
                        const earliestRefresh = dayjs(allTwilioPhoneNumbers.lastRefreshedAt).add(
                            TWILIO_CHANNELS_MIN_REFRESH_INTERVAL_MINUTES,
                            'minutes'
                        )
                        if (now.isBefore(earliestRefresh)) {
                            return `You can refresh the phone numbers again ${earliestRefresh.from(now)}`
                        }
                    }
                    return ''
                },
        ],
    }),
])
