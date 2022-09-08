import { kea, path, connect } from 'kea'
import { urlToAction } from 'kea-router'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import type { signupLogicType } from './signupLogicType'

export interface AccountResponse {
    success: boolean
    redirect_url?: string
    errorCode?: string
    errorDetail?: string
    errorAttribute?: string
}

export interface SignupForm {
    email: string
    password: string
    first_name: string
    organization_name: string
}

export const signupLogic = kea<signupLogicType>([
    path(['scenes', 'authentication', 'signupLogic']),
    connect({
        values: [preflightLogic, ['preflight']],
    }),
    forms(({ actions, values }) => ({
        signup: {
            defaults: { email: '', password: '', first_name: '', organization_name: '' } as SignupForm,
            errors: ({ email, password, first_name, organization_name }) => ({
                email: !email ? 'Please enter your email to continue' : undefined,
                password: !values.preflight?.demo
                    ? !password
                        ? 'Please enter your password to continue'
                        : password.length < 8
                        ? 'Password must be at least 8 characters'
                        : undefined
                    : undefined,
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                await breakpoint()
                try {
                    const res = await api.create('api/signup/', payload)
                    location.href = res.redirect_url || '/'
                } catch (e) {
                    actions.setSignupManualErrors({
                        generic: {
                            code: (e as Record<string, any>).code,
                            detail: (e as Record<string, any>).detail,
                        },
                    })
                    throw e
                }
            },
        },
    })),
    urlToAction(({ actions }) => ({
        '/signup': ({}, { email, values }) => {
            if (email) {
                if (values.preflight?.demo) {
                    // In demo mode no password is needed, so we can log in right away
                    // This allows us to give a quick login link in the `generate_demo_data` command
                    // X and Y are placeholders, irrelevant because the account should already exists
                    actions.setSignupValues({
                        email,
                        first_name: 'X',
                        organization_name: 'Y',
                    })
                } else {
                    actions.setSignupValue('email', email)
                }
            }
        },
    })),
])
