import { kea, path } from 'kea'
import { urlToAction } from 'kea-router'
import { forms } from 'kea-forms'
import api from 'lib/api'
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
    forms(({ actions }) => ({
        signup: {
            defaults: {} as unknown as SignupForm,
            errors: ({ email, password, first_name, organization_name }) => ({
                email: !email ? 'Please enter your email to continue' : undefined,
                password: !password
                    ? 'Please enter your password to continue'
                    : password.length < 8
                    ? 'Password must be at least 8 characters'
                    : undefined,
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                alert(JSON.stringify(payload))
                await breakpoint()
                try {
                    const res = await api.create('api/signup/', payload)
                    location.href = res.redirect_url || '/'
                } catch (e) {
                    console.log(e)
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
        '/signup': ({}, { email }) => {
            if (email) {
                actions.setSignupValue('email', email)
            }
        },
    })),
])
