import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { userLogic } from 'scenes/userLogic'

import type { timeSensitiveAuthenticationLogicType } from './timeSensitiveAuthenticationLogicType'

export interface ReauthenticationForm {
    password: string
    token?: string
}

const LOOKAHEAD_EXPIRY_SECONDS = 60 * 5

export const timeSensitiveAuthenticationLogic = kea<timeSensitiveAuthenticationLogicType>([
    path(['lib', 'components', 'timeSensitiveAuthenticationLogic']),
    connect({
        values: [apiStatusLogic, ['timeSensitiveAuthenticationRequired'], userLogic, ['user']],
        actions: [apiStatusLogic, ['setTimeSensitiveAuthenticationRequired'], userLogic, ['loadUser']],
    }),
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
                    const { code, status } = e as Record<string, any>
                    if (code === '2fa_required') {
                        actions.setRequiresTwoFactor(true)
                        throw e
                    }

                    if (status === 401) {
                        return { password: 'Incorrect password' }
                    }
                    throw e
                }

                actions.setTimeSensitiveAuthenticationRequired(false)
                // Refresh the user so we know the new session expiry
                actions.loadUser()
            },
        },
    })),

    selectors({
        showAuthenticationModal: [
            (s) => [s.timeSensitiveAuthenticationRequired, s.dismissedReauthentication],
            (timeSensitiveAuthenticationRequired, dismissedReauthentication) => {
                return timeSensitiveAuthenticationRequired && !dismissedReauthentication
            },
        ],

        sensitiveSessionExpiresAt: [
            (s) => [s.user],
            (user): Dayjs => {
                return dayjs(user?.sensitive_session_expires_at)
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        checkReauthentication: () => {
            if (values.sensitiveSessionExpiresAt.diff(dayjs(), 'seconds') < LOOKAHEAD_EXPIRY_SECONDS) {
                // Here we try to offer a better UX by forcing re-authentication if they are about to timeout which is nicer
                // than when they try to do something later and get a 403
                actions.setTimeSensitiveAuthenticationRequired(true)
            }
        },
    })),
])
