import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { emailMFAVerifyLogicType } from './emailMFAVerifyLogicType'
import { handleLoginRedirect } from './loginLogic'

export const emailMFAVerifyLogic = kea<emailMFAVerifyLogicType>([
    path(['scenes', 'authentication', 'emailMFAVerifyLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setGeneralError: (code, detail) => ({ code, detail }),
        clearGeneralError: true,
        setEmailAndToken: (email: string, token: string) => ({ email, token }),
        setView: (view: 'ready' | 'invalid') => ({ view }),
        verifyAndLogin: true,
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
        view: [
            'ready' as 'ready' | 'invalid',
            {
                setView: (_, { view }) => view,
            },
        ],
        email: [
            '' as string,
            {
                setEmailAndToken: (_, { email }) => email,
            },
        ],
        token: [
            '' as string,
            {
                setEmailAndToken: (_, { token }) => token,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
        verifyResponse: [
            null as { success: boolean } | null,
            {
                verifyAndLogin: async () => {
                    try {
                        // Validate token AND log in (single endpoint)
                        const response = await api.create<any>('api/login/email-mfa', {
                            email: values.email,
                            token: values.token,
                        })

                        // Login successful - redirect to app
                        handleLoginRedirect()
                        window.location.reload()

                        return response
                    } catch (e) {
                        const { code, detail } = e as Record<string, any>
                        actions.setGeneralError(code, detail)
                        actions.setView('invalid')
                        throw e
                    }
                },
            },
        ],
    })),
    urlToAction(({ actions }) => ({
        '/login/verify': (_, { email, token }) => {
            if (email && token) {
                // Store email and token, show ready view (no API call yet)
                actions.setEmailAndToken(email, token)
                actions.setView('ready')
            } else {
                actions.setGeneralError('invalid_link', 'Invalid verification link. Please try logging in again.')
                actions.setView('invalid')
            }
        },
    })),
])
