import { kea, path, connect, actions, reducers } from 'kea'
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
    role_at_organization: string
}

export const emailRegex: RegExp =
    /(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])/

export const signupLogic = kea<signupLogicType>([
    path(['scenes', 'authentication', 'signupLogic']),
    connect({
        values: [preflightLogic, ['preflight']],
    }),
    actions({
        setPanel: (panel: number) => ({ panel }),
    }),
    reducers({
        panel: [
            0,
            {
                setPanel: (_, { panel }) => panel,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        signupPanel1: {
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            defaults: {
                email: '',
                password: '',
            } as SignupForm,
            errors: ({ email, password }) => ({
                email: !email
                    ? 'Please enter your email to continue'
                    : !emailRegex.test(email)
                    ? 'Please use a valid email address'
                    : undefined,
                password: !values.preflight?.demo
                    ? !password
                        ? 'Please enter your password to continue'
                        : password.length < 8
                        ? 'Password must be at least 8 characters'
                        : undefined
                    : undefined,
            }),
            submit: async () => {
                actions.setPanel(1)
            },
        },
        signupPanel2: {
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            defaults: {
                first_name: '',
                organization_name: '',
                role_at_organization: '',
            } as SignupForm,
            errors: ({ first_name, organization_name }) => ({
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                await breakpoint()
                try {
                    const res = await api.create('api/signup/', { ...values.signupPanel1, ...payload })
                    location.href = res.redirect_url || '/'
                } catch (e) {
                    actions.setSignupPanel2ManualErrors({
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
    urlToAction(({ actions, values }) => ({
        '/signup': ({}, { email }) => {
            if (email) {
                if (values.preflight?.demo) {
                    // In demo mode no password is needed, so we can log in right away
                    // This allows us to give a quick login link in the `generate_demo_data` command
                    // X and Y are placeholders, irrelevant because the account should already exists
                    actions.setSignupPanel1Values({
                        email,
                    })
                    actions.setSignupPanel2Values({
                        first_name: 'X',
                        organization_name: 'Y',
                    })
                    actions.submitSignupPanel2()
                } else {
                    actions.setSignupPanel1Value('email', email)
                }
            }
        },
    })),
])
