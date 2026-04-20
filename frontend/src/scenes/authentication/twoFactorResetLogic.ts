import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { loginLogic } from './loginLogic'
import type { twoFactorResetLogicType } from './twoFactorResetLogicType'

export interface ValidatedTokenResponse {
    success: boolean
    token?: string
    error?: string
    requires_login?: boolean
}

export interface ResetResponse {
    success: boolean
    error?: string
    requires_login?: boolean
}

export const twoFactorResetLogic = kea<twoFactorResetLogicType>([
    path(['scenes', 'authentication', 'twoFactorResetLogic']),
    actions({
        confirmReset: (token: string) => ({ token }),
        setResetComplete: (complete: boolean) => ({ complete }),
        setResetError: (error: string | null) => ({ error }),
        setRequiresLogin: (requires: boolean) => ({ requires }),
        resetState: true,
    }),
    loaders(({ actions }) => ({
        validatedResetToken: [
            null as ValidatedTokenResponse | null,
            {
                validateResetToken: async ({ uuid, token }: { uuid: string; token: string }) => {
                    try {
                        const response = await api.get<ValidatedTokenResponse>(`api/reset_2fa/${uuid}/?token=${token}`)
                        return response
                    } catch (e: any) {
                        const requiresLogin = e.data?.requires_login === true
                        if (requiresLogin) {
                            actions.setRequiresLogin(true)
                        }
                        return {
                            success: false,
                            error: e.data?.error || e.detail || 'Invalid or expired link',
                            requires_login: requiresLogin,
                        }
                    }
                },
            },
        ],
        resetResult: [
            null as ResetResponse | null,
            {
                executeReset: async ({ uuid, token }: { uuid: string; token: string }) => {
                    const response = await api.create<ResetResponse>(`api/reset_2fa/${uuid}/`, { token })
                    return response
                },
            },
        ],
    })),
    reducers({
        validatedResetToken: {
            resetState: () => null,
        },
        resetComplete: [
            false,
            {
                setResetComplete: (_, { complete }) => complete,
                resetState: () => false,
            },
        ],
        resetError: [
            null as string | null,
            {
                setResetError: (_, { error }) => error,
                executeReset: () => null,
                resetState: () => null,
            },
        ],
        resetLoading: [
            false,
            {
                executeReset: () => true,
                executeResetSuccess: () => false,
                executeResetFailure: () => false,
            },
        ],
        currentUuid: [
            '' as string,
            {
                validateResetToken: (_, { uuid }) => uuid,
            },
        ],
        currentToken: [
            '' as string,
            {
                validateResetToken: (_, { token }) => token,
            },
        ],
        requiresLogin: [
            false as boolean,
            {
                setRequiresLogin: (_, { requires }) => requires,
                validateResetTokenSuccess: (state, { validatedResetToken }) =>
                    validatedResetToken?.requires_login || state,
                resetState: () => false,
            },
        ],
    }),
    selectors({
        loginRedirectUrl: [
            (s) => [s.currentUuid, s.currentToken],
            (uuid, token): string => {
                // Redirect to login with the 2FA reset URL as the next parameter
                const resetUrl = urls.twoFactorReset(uuid, token)
                return `${urls.login()}?next=${encodeURIComponent(resetUrl)}`
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        confirmReset: async ({ token }) => {
            try {
                actions.executeReset({ uuid: values.currentUuid, token })
            } catch (e: any) {
                actions.setResetError(e.data?.error || e.detail || 'Failed to reset 2FA. Please try again.')
            }
        },
        executeResetSuccess: ({ resetResult }) => {
            if (resetResult?.success) {
                actions.setResetComplete(true)
                // Reset the login form state so user starts fresh when redirected to login
                loginLogic.actions.resetLogin()
            } else if (resetResult?.requires_login) {
                actions.setRequiresLogin(true)
            } else {
                actions.setResetError(resetResult?.error || 'Failed to reset 2FA. Please try again.')
            }
        },
        executeResetFailure: ({ error }) => {
            actions.setResetError(error || 'Failed to reset 2FA. Please try again.')
        },
    })),
    urlToAction(({ actions }) => ({
        '/reset_2fa/:uuid/:token': ({ uuid, token }) => {
            if (token && uuid) {
                actions.validateResetToken({ uuid, token })
            }
        },
    })),
])
