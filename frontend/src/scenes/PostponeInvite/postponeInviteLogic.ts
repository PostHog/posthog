import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { Dayjs, dayjs } from 'lib/dayjs'

import type { postponeInviteLogicType } from './postponeInviteLogicType'

// Handwritten to mirror the serializers in posthog/api/invite_postpone.py. Swap for the generated
// types (InvitePostponeInfoApi / InvitePostponeResultApi) once `hogli build:openapi` has run.
export interface PostponeInviteInfo {
    organization_name: string
    target_email: string | null
    inviter_first_name: string
    scheduled_send_at: string | null
    expires_at: string
}

export interface PostponeInviteResult {
    scheduled_send_at: string
    expires_at: string
}

export type PostponeOptionKey = 'hour' | 'tonight' | 'tomorrow'

// Wall-clock targets for the preset options, in the recipient's local (browser) timezone.
const TONIGHT_HOUR = 18
const TOMORROW_HOUR = 9

export const postponeInviteLogic = kea<postponeInviteLogicType>([
    path(['scenes', 'PostponeInvite', 'postponeInviteLogic']),
    actions({
        loadInvite: (token: string) => ({ token }),
        setCustomDate: (customDate: Dayjs | null) => ({ customDate }),
        postponeByOption: (option: PostponeOptionKey) => ({ option }),
        postponeCustom: true,
        setSubmittingOption: (option: PostponeOptionKey | 'custom') => ({ option }),
    }),
    loaders(({ values }) => ({
        invite: [
            null as PostponeInviteInfo | null,
            {
                loadInvite: async ({ token }) => {
                    return await api.get<PostponeInviteInfo>(`api/invite_postpone?token=${encodeURIComponent(token)}`)
                },
            },
        ],
        result: [
            null as PostponeInviteResult | null,
            {
                postpone: async ({ sendAt, option }: { sendAt: Dayjs; option: PostponeOptionKey | 'custom' }) => {
                    return await api.create<PostponeInviteResult>('api/invite_postpone', {
                        token: values.token,
                        send_at: sendAt.toISOString(),
                        option,
                    })
                },
            },
        ],
    })),
    reducers({
        token: ['' as string, { loadInvite: (_, { token }) => token }],
        customDate: [null as Dayjs | null, { setCustomDate: (_, { customDate }) => customDate }],
        // Which option is mid-request, so only the clicked button shows a spinner.
        submittingOption: [
            null as PostponeOptionKey | 'custom' | null,
            {
                setSubmittingOption: (_, { option }) => option,
                postponeSuccess: () => null,
                postponeFailure: () => null,
            },
        ],
        loadErrorMessage: [
            null as string | null,
            {
                loadInvite: () => null,
                loadInviteFailure: (_, { errorObject }) =>
                    (errorObject as ApiError)?.detail ?? 'This link is invalid or has expired.',
            },
        ],
        submitErrorMessage: [
            null as string | null,
            {
                postpone: () => null,
                postponeFailure: (_, { errorObject }) =>
                    (errorObject as ApiError)?.detail ?? 'Something went wrong. Please try again.',
            },
        ],
    }),
    selectors({
        // "Tonight" only makes sense while it's still before the evening cutoff.
        tonightAvailable: [() => [], (): boolean => dayjs().hour() < TONIGHT_HOUR],
    }),
    listeners(({ actions, values }) => ({
        // Compute the absolute target at click time (not at mount) so "in an hour" stays accurate.
        postponeByOption: ({ option }) => {
            let sendAt: Dayjs
            if (option === 'hour') {
                sendAt = dayjs().add(1, 'hour')
            } else if (option === 'tonight') {
                sendAt = dayjs().hour(TONIGHT_HOUR).minute(0).second(0).millisecond(0)
            } else {
                sendAt = dayjs().add(1, 'day').hour(TOMORROW_HOUR).minute(0).second(0).millisecond(0)
            }
            actions.setSubmittingOption(option)
            actions.postpone({ sendAt, option })
        },
        postponeCustom: () => {
            if (values.customDate) {
                actions.setSubmittingOption('custom')
                actions.postpone({ sendAt: values.customDate, option: 'custom' })
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadInvite(router.values.searchParams['token'] ?? '')
    }),
])
