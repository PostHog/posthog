import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { emailMFAVerifyLogicType } from './emailMFAVerifyLogicType'
import { handleLoginRedirect } from './loginLogic'

export interface EmailMFAVerifyForm {
    email: string
    token: string
}

export const emailMFAVerifyLogic = kea<emailMFAVerifyLogicType>([
    path(['scenes', 'authentication', 'emailMFAVerifyLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setGeneralError: (code, detail) => ({ code, detail }),
        clearGeneralError: true,
        setEmailAndToken: (email, token) => ({ email, token }),
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
    }),
    forms(({ actions }) => ({
        emailMFAVerify: {
            defaults: { email: '', token: '' } as EmailMFAVerifyForm,
            submit: async ({ email, token }, breakpoint) => {
                breakpoint()
                try {
                    return await api.create<any>('api/login/email-mfa', {
                        email,
                        token,
                    })
                } catch (e) {
                    const { code, detail } = e as Record<string, any>
                    actions.setGeneralError(code, detail)
                    throw e
                }
            },
        },
    })),
    listeners({
        submitEmailMFAVerifySuccess: () => {
            handleLoginRedirect()
            window.location.reload()
        },
        setEmailAndToken: ({ email, token }) => {
            emailMFAVerifyLogic.actions.setEmailMFAVerifyValue('email', email)
            emailMFAVerifyLogic.actions.setEmailMFAVerifyValue('token', token)
            emailMFAVerifyLogic.actions.submitEmailMFAVerify()
        },
    }),
    urlToAction(({ actions }) => ({
        '/login/verify': (_, { email, token }) => {
            if (email && token) {
                actions.setEmailAndToken(email, token)
            } else {
                actions.setGeneralError('invalid_link', 'Invalid verification link. Please try logging in again.')
            }
        },
    })),
])
