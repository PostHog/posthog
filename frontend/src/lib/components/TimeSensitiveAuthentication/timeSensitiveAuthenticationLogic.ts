import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { PrecheckResponseType } from 'scenes/authentication/loginLogic'
import { userLogic } from 'scenes/userLogic'

import { modalInterruptionTrackingLogic } from './modalInterruptionTrackingLogic'
import type { timeSensitiveAuthenticationLogicType } from './timeSensitiveAuthenticationLogicType'

export interface ReauthenticationForm {
    password: string
    token?: string
}

const LOOKAHEAD_EXPIRY_SECONDS = 60 * 5

export const timeSensitiveAuthenticationLogic = kea<timeSensitiveAuthenticationLogicType>([
    path(['lib', 'components', 'timeSensitiveAuthenticationLogic']),
    connect(() => ({
        values: [
            apiStatusLogic,
            ['timeSensitiveAuthenticationRequired'],
            userLogic,
            ['user'],
            modalInterruptionTrackingLogic,
            ['interruptedForm'],
        ],
        actions: [apiStatusLogic, ['setTimeSensitiveAuthenticationRequired'], userLogic, ['loadUser']],
        logic: [modalInterruptionTrackingLogic],
    })),
    actions({
        setDismissedReauthentication: (value: boolean) => ({ value }),
        setRequiresTwoFactor: (value: boolean) => ({ value }),
        checkReauthentication: true,
    }),
    reducers({
        dismissedReauthentication: [
            false,
            {
                setDismissedReauthentication: (_, { value }) => value,
                setTimeSensitiveAuthenticationRequired: () => false,
            },
        ],

        twoFactorRequired: [
            false,
            {
                setRequiresTwoFactor: (_, { value }) => value,
            },
        ],
    }),

    loaders(({ values }) => ({
        precheckResponse: [
            null as PrecheckResponseType | null,
            {
                precheck: async () => {
                    const response = await api.create('api/login/precheck', { email: values.user!.email })
                    return { status: 'completed', ...response }
                },
            },
        ],
    })),

    forms(({ actions, values }) => ({
        reauthentication: {
            defaults: {} as unknown as ReauthenticationForm,
            errors: ({ password, token }) => ({
                password: !password ? 'Please enter your password to continue' : undefined,
                token: values.twoFactorRequired && !token ? 'Please enter your 2FA code' : undefined,
            }),
            submit: async ({ password, token }, breakpoint): Promise<any> => {
                const email = userLogic.findMounted()?.values.user?.email
                await breakpoint(150)

                try {
                    if (!token) {
                        await api.create('api/login', { email, password })
                    } else {
                        await api.create('api/login/token', { token })
                    }
                } catch (e) {
                    const { code } = e as Record<string, any>
                    if (code === '2fa_required') {
                        actions.setRequiresTwoFactor(true)
                    }
                    if (code === 'invalid_credentials') {
                        actions.setReauthenticationManualErrors({ password: 'Incorrect password' })
                    }

                    throw e
                }
            },
        },
    })),

    selectors({
        showAuthenticationModal: [
            (s) => [s.timeSensitiveAuthenticationRequired, s.dismissedReauthentication],
            (timeSensitiveAuthenticationRequired, dismissedReauthentication): boolean => {
                return !!timeSensitiveAuthenticationRequired && !dismissedReauthentication
            },
        ],

        sensitiveSessionExpiresAt: [
            (s) => [s.user],
            (user): Dayjs => {
                return dayjs(user?.sensitive_session_expires_at)
            },
        ],
    }),

    subscriptions(({ values, actions }) => ({
        showAuthenticationModal: (shown) => {
            if (shown) {
                posthog.capture('reauthentication_modal_shown', {
                    interrupted_form: values.interruptedForm,
                })

                const modalTrackingLogic = modalInterruptionTrackingLogic.findMounted()
                if (modalTrackingLogic) {
                    modalTrackingLogic.actions.setInterruptedForm(null)
                }

                if (!values.precheckResponse) {
                    actions.precheck()
                }
            }
        },
    })),

    listeners(({ actions, values }) => ({
        submitReauthenticationSuccess: () => {
            if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                values.timeSensitiveAuthenticationRequired[0]() // Resolve
            }
            posthog.capture('reauthentication_completed')
            actions.setTimeSensitiveAuthenticationRequired(false)
            // Refresh the user so we know the new session expiry
            actions.loadUser()
        },
        submitReauthenticationFailure: () => {
            if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                values.timeSensitiveAuthenticationRequired[1]() // Reject
            }
        },
        setDismissedReauthentication: ({ value }) => {
            if (value) {
                if (Array.isArray(values.timeSensitiveAuthenticationRequired)) {
                    values.timeSensitiveAuthenticationRequired[1]() // Reject
                }
                posthog.capture('reauthentication_modal_dismissed')
            }
        },
        checkReauthentication: () => {
            if (values.sensitiveSessionExpiresAt.diff(dayjs(), 'seconds') < LOOKAHEAD_EXPIRY_SECONDS) {
                // Here we try to offer a better UX by forcing re-authentication if they are about to timeout
                // which is nicer than when they try to do something later and get a 403.
                // We also make this a promise, so that `checkReauthentication` callsites can await
                // `asyncActions.checkReauthentication()` and proceed once re-authentication is completed
                return new Promise((resolve, reject) =>
                    actions.setTimeSensitiveAuthenticationRequired([resolve, reject])
                )
            }
        },
    })),
])
