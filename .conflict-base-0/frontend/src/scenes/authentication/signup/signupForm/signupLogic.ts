import { isString } from '@tiptap/core'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ValidatedPasswordResult, validatePassword } from 'lib/components/PasswordStrength'
import { CLOUD_HOSTNAMES, FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getRelativeNextPath } from 'lib/utils'
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
    // oxlint-disable-next-line no-control-regex
    /(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])/

export const signupLogic = kea<signupLogicType>([
    path(['scenes', 'authentication', 'signupLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions(() => ({
        setPanel: (panel: number) => ({ panel }),
        normalizeEmailWithDelay: (email: string) => ({ email }),
        setEmailNormalized: (wasNormalized: boolean) => ({ wasNormalized }),
    })),
    reducers(() => ({
        panel: [
            0,
            {
                setPanel: (_, { panel }) => panel,
            },
        ],
        emailWasNormalized: [
            false,
            {
                setEmailNormalized: (_, { wasNormalized }) => wasNormalized,
            },
        ],
    })),
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
                        : values.validatedPassword.feedback || undefined
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
            errors: ({ name, role_at_organization }) => ({
                name: !name ? 'Please enter your name' : undefined,
                role_at_organization: !role_at_organization ? 'Please select your role in the organization' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                breakpoint()
                try {
                    const nextUrl = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)

                    const res = await api.create('api/signup/', {
                        ...values.signupPanel1,
                        ...payload,
                        first_name: payload.name.split(' ')[0],
                        last_name: payload.name.split(' ')[1] || undefined,
                        organization_name: payload.organization_name || undefined,
                        next_url: nextUrl ?? undefined,
                    })

                    if (!payload.organization_name) {
                        posthog.capture('sign up organization name not provided')
                    }

                    location.href = res.redirect_url || '/'
                } catch (e) {
                    const error = e as Record<string, any>

                    if (error.code === 'throttled') {
                        actions.setSignupPanel2ManualErrors({
                            generic: {
                                code: error.code,
                                detail: 'Too many signup attempts. Please try again later.',
                            },
                        })
                    } else {
                        actions.setSignupPanel2ManualErrors({
                            generic: {
                                code: error.code,
                                detail: error.detail,
                            },
                        })
                    }
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
        emailCaseNotice: [
            (s) => [s.emailWasNormalized],
            (emailWasNormalized): string | undefined => {
                return emailWasNormalized ? '⚠ Your email was automatically converted to lowercase' : undefined
            },
        ],
        loginUrl: [
            () => [router.selectors.searchParams],
            (searchParams: Record<string, string>) => {
                const nextParam = getRelativeNextPath(searchParams['next'], location)
                return nextParam ? `/login?next=${encodeURIComponent(nextParam)}` : '/login'
            },
        ],
    }),
    listeners(({ actions }) => ({
        normalizeEmailWithDelay: async ({ email }, breakpoint) => {
            await breakpoint(500)

            const hasUppercase = /[A-Z]/.test(email)
            if (hasUppercase) {
                const normalizedEmail = email.toLowerCase()
                actions.setSignupPanel1Value('email', normalizedEmail)
                actions.setEmailNormalized(true)
            }
        },
        setSignupPanel1Value: ({ name, value }) => {
            if (name.toString() === 'email' && typeof value === 'string') {
                actions.setEmailNormalized(false)
                actions.normalizeEmailWithDelay(value)
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/signup': (_, { email, maintenanceRedirect }) => {
            if (values.preflight?.cloud) {
                // Redirect to a different region if we are doing maintenance on one of them
                const regionOverrideFlag = values.featureFlags[FEATURE_FLAGS.REDIRECT_SIGNUPS_TO_INSTANCE]
                const regionsAllowList = ['eu', 'us']
                const isRegionOverrideValid =
                    isString(regionOverrideFlag) && regionsAllowList.includes(regionOverrideFlag)
                // KLUDGE: the backend can technically return null
                // and, we don't want to redirect to the app unless the preflight region is valid
                const isPreflightRegionValid =
                    values.preflight?.region && regionsAllowList.includes(values.preflight?.region)

                if (
                    isRegionOverrideValid &&
                    isPreflightRegionValid &&
                    regionOverrideFlag !== values.preflight?.region?.toLowerCase()
                ) {
                    window.location.href = `https://${
                        CLOUD_HOSTNAMES[regionOverrideFlag.toUpperCase() as keyof typeof CLOUD_HOSTNAMES]
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
