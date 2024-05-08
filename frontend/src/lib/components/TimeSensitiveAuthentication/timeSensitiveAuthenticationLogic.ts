import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { userLogic } from 'scenes/userLogic'

import type { timeSensitiveAuthenticationLogicType } from './timeSensitiveAuthenticationLogicType'

export interface ReauthenticationForm {
    password: string
    token?: string
}

export const timeSensitiveAuthenticationLogic = kea<timeSensitiveAuthenticationLogicType>([
    path(['lib', 'components', 'timeSensitiveAuthenticationLogic']),
    connect({
        values: [apiStatusLogic, ['timeSensitiveAuthenticationRequired']],
        actions: [apiStatusLogic, ['setTimeSensitiveAuthenticationRequired']],
    }),
    actions({
        setDismissedReauthentication: (dismissed: boolean) => ({ dismissed }),
        setRequiresTwoFactor: (twoFactorRequired: boolean) => ({ twoFactorRequired }),
    }),
    reducers({
        dismissedReauthentication: [
            false,
            {
                setDismissedReauthentication: (_, { dismissed }) => dismissed,
                setTimeSensitiveAuthenticationRequired: () => false,
            },
        ],

        twoFactorRequired: [
            false,
            {
                setRequiresTwoFactor: (_, { twoFactorRequired }) => twoFactorRequired,
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
                    const { code, status, detail } = e as Record<string, any>
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
    }),
])
