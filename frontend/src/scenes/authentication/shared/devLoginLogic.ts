import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { devLoginLogicType } from './devLoginLogicType'

export interface DevUser {
    email: string
    is_staff: boolean
    label: string | null
}

export const DEV_LOGIN_SECONDS_SAVED_PER_CLICK = 5

export const DEV_LOGIN_DEFAULT_EMAIL = 'test@posthog.com'

export const devLoginLogic = kea<devLoginLogicType>([
    path(['scenes', 'authentication', 'shared', 'devLoginLogic']),
    actions({
        devLogin: (email: string) => ({ email }),
    }),
    reducers({
        devLoginCount: [
            0,
            { persist: true },
            {
                devLogin: (count) => count + 1,
            },
        ],
    }),
    loaders(() => ({
        devUsers: [
            [] as DevUser[],
            {
                // Not fired on an `onMount` because we don't always need it.
                loadDevUsers: async (_, breakpoint) => {
                    breakpoint()
                    try {
                        const response = await api.get<{ users: DevUser[] }>('api/login/dev')
                        // Pin the default seeded user to the top; the rest keep the backend's alphabetical order.
                        const users = [...response.users]
                        const defaultIndex = users.findIndex((u) => u.email === DEV_LOGIN_DEFAULT_EMAIL)
                        if (defaultIndex > 0) {
                            users.unshift(...users.splice(defaultIndex, 1))
                        }
                        return users
                    } catch {
                        // Endpoint is unavailable unless allow_dev_login is set in preflight.
                        return []
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        devLoginTimeSavedLabel: [
            (s) => [s.devLoginCount],
            (devLoginCount): string | null => {
                if (devLoginCount === 0) {
                    return null
                }

                const totalSeconds = devLoginCount * DEV_LOGIN_SECONDS_SAVED_PER_CLICK
                if (totalSeconds < 60) {
                    const unit = totalSeconds === 1 ? 'second' : 'seconds'
                    return `You've saved ${totalSeconds} ${unit} by clicking this button.`
                }

                const minutes = Math.floor(totalSeconds / 60)
                const unit = minutes === 1 ? 'minute' : 'minutes'
                return `You've saved ${minutes} ${unit} by clicking this button.`
            },
        ],
    })),
    listeners(() => ({
        devLogin: async ({ email }) => {
            // Dynamic import to avoid a circular dependency: loginLogic statically imports this logic.
            const { loginLogic, handleLoginRedirect } = await import('scenes/authentication/login/loginLogic')
            loginLogic.actions.clearGeneralError()
            try {
                await api.create<any>('api/login/dev', { email })
            } catch (e) {
                const { code, detail } = e as Record<string, any>
                loginLogic.actions.setGeneralError(code || 'dev_login_failed', detail || 'Dev login failed')
                return
            }
            handleLoginRedirect()
            window.location.reload()
        },
    })),
])
