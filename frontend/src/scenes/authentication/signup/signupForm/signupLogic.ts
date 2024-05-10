import { lemonToast } from '@posthog/lemon-ui'
import { isString } from '@tiptap/core'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { ValidatedPasswordResult, validatePassword } from 'lib/components/PasswordStrength'
import { CLOUD_HOSTNAMES, FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

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
    name: string
    organization_name: string
    role_at_organization: string
    referral_source: string
}

export const emailRegex: RegExp =
    // eslint-disable-next-line no-control-regex
    /(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])/

export const signupLogic = kea<signupLogicType>([
    path(['scenes', 'authentication', 'signupLogic']),
    connect({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
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
                        : values.validatedPassword.feedback
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
                name: '',
                organization_name: '',
                role_at_organization: '',
                referral_source: '',
            } as SignupForm,
            errors: ({ name }) => ({
                name: !name ? 'Please enter your name' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                breakpoint()
                try {
                    const res = await api.create('api/signup/', {
                        ...values.signupPanel1,
                        ...payload,
                        first_name: payload.name.split(' ')[0],
                        last_name: payload.name.split(' ')[1] || undefined,
                        organization_name: payload.organization_name || undefined,
                    })
                    if (!payload.organization_name) {
                        posthog.capture('sign up organization name not provided')
                    }
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
    selectors({
        validatedPassword: [
            (s) => [s.signupPanel1],
            ({ password }): ValidatedPasswordResult => {
                return validatePassword(password)
            },
        ],
    }),
    urlToAction(({ actions, values }) => ({
        '/signup': (_, { email, maintenanceRedirect }) => {
            if (values.preflight?.cloud) {
                // Redirect to a different region if we are doing maintenance on one of them
                const regionOverrideFlag = values.featureFlags[FEATURE_FLAGS.REDIRECT_SIGNUPS_TO_INSTANCE]
                const regionsAllowList = ['eu', 'us']
                const isRegionOverrideValid =
                    isString(regionOverrideFlag) && regionsAllowList.includes(regionOverrideFlag)
                // KLUDGE: the backend can technically return null
                // but definitely does in Cypress tests
                // and, we don't want to redirect to the app unless the preflight region is valid
                const isPreflightRegionValid =
                    values.preflight?.region && regionsAllowList.includes(values.preflight?.region)

                if (
                    isRegionOverrideValid &&
                    isPreflightRegionValid &&
                    regionOverrideFlag !== values.preflight?.region?.toLowerCase()
                ) {
                    window.location.href = `https://${
                        CLOUD_HOSTNAMES[regionOverrideFlag.toUpperCase()]
                    }${urls.signup()}?maintenanceRedirect=true`
                }
                if (maintenanceRedirect && isRegionOverrideValid) {
                    lemonToast.info(
                        `You've been redirected to signup on our ${regionOverrideFlag.toUpperCase()} instance while we perform maintenance on our other instance.`
                    )
                }
            }
            if (email) {
                if (values.preflight?.demo) {
                    // In demo mode no password is needed, so we can log in right away
                    // This allows us to give a quick login link in the `generate_demo_data` command
                    // X and Y are placeholders, irrelevant because the account should already exists
                    actions.setSignupPanel1Values({
                        email,
                    })
                    actions.setSignupPanel2Values({
                        name: 'X',
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
