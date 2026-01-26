import { startRegistration } from '@simplewebauthn/browser'
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
import { RegistrationBeginResponse } from 'scenes/settings/user/passkeySettingsLogic'
import { getPasskeyErrorMessage } from 'scenes/settings/user/passkeys/utils'
import { urls } from 'scenes/urls'

import type { signupLogicType } from './signupLogicType'

export interface AccountResponse {
    success: boolean
    redirect_url?: string
    errorCode?: string
    errorDetail?: string
    errorAttribute?: string
}

export interface SignupPanelEmailForm {
    email: string
}

export interface SignupPanelAuthForm {
    password: string
}

export interface SignupPanelOnboardingForm {
    name: string
    organization_name: string
    role_at_organization: string
    referral_source: string
}

interface SignupEmailPrecheckResponse {
    email_exists: boolean
    code?: string
    detail?: string
}

// Keep SignupForm for backwards compatibility
export interface SignupForm extends SignupPanelEmailForm, SignupPanelAuthForm, SignupPanelOnboardingForm {}

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
        // Passkey actions
        registerPasskey: true,
        setPasskeyRegistered: (registered: boolean) => ({ registered }),
        setPasskeyRegistering: (registering: boolean) => ({ registering }),
        setPasskeyError: (error: string | null) => ({ error }),
        setError: (error: string | null) => ({ error }),
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
        passkeyRegistered: [
            false,
            {
                setPasskeyRegistered: (_, { registered }) => registered,
            },
        ],
        isPasskeyRegistering: [
            false,
            {
                setPasskeyRegistering: (_, { registering }) => registering,
            },
        ],
        passkeyError: [
            null as string | null,
            {
                setPasskeyError: (_, { error }) => error,
                registerPasskey: () => null,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
            },
        ],
    })),
    forms(({ actions, values }) => ({
        signupPanelEmail: {
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            defaults: {
                email: '',
            } as SignupPanelEmailForm,
            errors: ({ email }) => ({
                email: !email
                    ? 'Please enter your email to continue'
                    : !emailRegex.test(email)
                      ? 'Please use a valid email address'
                      : undefined,
            }),
            submit: async ({ email }, breakpoint) => {
                breakpoint()
                actions.setSignupPanelEmailManualErrors({})
                actions.setPasskeyError(null)
                actions.setError(null)
                try {
                    await api.create<SignupEmailPrecheckResponse>('api/signup/precheck', {
                        email,
                    })
                } catch (e: any) {
                    if (e?.status === 409 || e?.code === 'account_exists') {
                        const errorMessage = e?.detail || 'There is already an account with this email address.'
                        actions.setSignupPanelEmailManualErrors({
                            email: errorMessage,
                        })
                        actions.setError(errorMessage)
                        actions.setPanel(0)
                        return
                    }
                    actions.setSignupPanelEmailManualErrors({
                        email: e?.detail || 'Could not verify your email. Please try again.',
                    })
                    return
                }
                actions.setPanel(1)
            },
        },
        signupPanelAuth: {
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            defaults: {
                password: '',
            } as SignupPanelAuthForm,
            errors: ({ password }) => ({
                // Password not required if passkey is registered
                password:
                    !values.passkeyRegistered && !values.preflight?.demo
                        ? !password
                            ? 'Please enter your password to continue'
                            : values.validatedPassword.feedback || undefined
                        : undefined,
            }),
            submit: async () => {
                actions.setPanel(2)
            },
        },
        signupPanelOnboarding: {
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            defaults: {
                name: '',
                organization_name: '',
                role_at_organization: '',
                referral_source: '',
            } as SignupPanelOnboardingForm,
            errors: ({ name, role_at_organization }) => ({
                name: !name ? 'Please enter your name' : undefined,
                role_at_organization: !role_at_organization ? 'Please select your role in the organization' : undefined,
            }),
            submit: async (payload, breakpoint) => {
                breakpoint()
                try {
                    const nextUrl = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)

                    const signupData: Record<string, any> = {
                        email: values.signupPanelEmail.email,
                        first_name: payload.name.split(' ')[0],
                        last_name: payload.name.split(' ')[1] || undefined,
                        organization_name: payload.organization_name || undefined,
                        role_at_organization: payload.role_at_organization,
                        referral_source: payload.referral_source,
                        next_url: nextUrl ?? undefined,
                    }

                    // Only include password for password-based signup
                    if (!values.passkeyRegistered && values.signupPanelAuth.password) {
                        signupData.password = values.signupPanelAuth.password
                    }

                    const res = await api.create('api/signup/', signupData)

                    if (!payload.organization_name) {
                        posthog.capture('sign up organization name not provided')
                    }

                    if (values.passkeyRegistered) {
                        posthog.capture('signup completed with passkey')
                    }

                    // it's ok to trust the url sent from the server
                    // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                    location.href = res.redirect_url || '/'
                } catch (e) {
                    const error = e as Record<string, any>

                    if (error.code === 'throttled') {
                        actions.setSignupPanelOnboardingManualErrors({
                            generic: {
                                code: error.code,
                                detail: 'Too many signup attempts. Please try again later.',
                            },
                        })
                    } else {
                        actions.setSignupPanelOnboardingManualErrors({
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
        // Legacy forms for backwards compatibility during transition
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
            submit: async ({ email }, breakpoint) => {
                breakpoint()
                actions.setSignupPanel1ManualErrors({})
                let precheckResponse: SignupEmailPrecheckResponse
                try {
                    precheckResponse = await api.create<SignupEmailPrecheckResponse>('api/signup/precheck', {
                        email,
                    })
                } catch (e: any) {
                    if (e?.status === 409 || e?.code === 'account_exists') {
                        actions.setSignupPanel1ManualErrors({
                            email: 'There is already an account with this email address.',
                        })
                        actions.setPanel(0)
                        return
                    }
                    actions.setSignupPanel1ManualErrors({
                        email: e?.detail || 'Could not verify your email. Please try again.',
                    })
                    return
                }
                if (precheckResponse.email_exists || precheckResponse.code === 'account_exists') {
                    actions.setSignupPanel1ManualErrors({
                        email: precheckResponse.detail || 'There is already an account with this email address.',
                    })
                    actions.setPanel(0)
                    return
                }
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

                    // it's ok to trust the url sent from the server
                    // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
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
            (s) => [s.signupPanelAuth, s.signupPanel1],
            (signupPanelAuth, signupPanel1): ValidatedPasswordResult => {
                // Use new form if available, fallback to legacy
                const password = signupPanelAuth.password || signupPanel1.password
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
        passkeySignupEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                return !!featureFlags[FEATURE_FLAGS.PASSKEY_SIGNUP_ENABLED]
            },
        ],
        panelTitle: [
            (s) => [s.panel, s.passkeySignupEnabled, s.preflight],
            (panel: number, passkeySignupEnabled: boolean, preflight): string => {
                if (preflight?.demo) {
                    return 'Explore PostHog yourself'
                }

                if (passkeySignupEnabled) {
                    switch (panel) {
                        case 0:
                            return 'Get started'
                        case 1:
                            return 'Choose how to sign in'
                        case 2:
                            return 'Tell us a bit about yourself'
                        default:
                            return 'Get started'
                    }
                }

                return panel === 0 ? 'Get started' : 'Tell us a bit about yourself'
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        normalizeEmailWithDelay: async ({ email }, breakpoint) => {
            await breakpoint(500)

            const hasUppercase = /[A-Z]/.test(email)
            if (hasUppercase) {
                const normalizedEmail = email.toLowerCase()
                // Normalize for both form systems
                if (values.passkeySignupEnabled) {
                    actions.setSignupPanelEmailValue('email', normalizedEmail)
                } else {
                    actions.setSignupPanel1Value('email', normalizedEmail)
                }
                actions.setEmailNormalized(true)
            }
        },
        setSignupPanelEmailValue: ({ name, value }) => {
            if (name.toString() === 'email' && typeof value === 'string') {
                actions.setEmailNormalized(false)
                actions.normalizeEmailWithDelay(value)
            }
        },
        setSignupPanel1Value: ({ name, value }) => {
            if (name.toString() === 'email' && typeof value === 'string') {
                actions.setEmailNormalized(false)
                actions.normalizeEmailWithDelay(value)
            }
        },
        setPasskeyRegistered: ({ registered }) => {
            if (registered) {
                // Advance to onboarding panel after successful passkey registration
                actions.setPanel(2)
            }
        },
        registerPasskey: async () => {
            const email = values.signupPanelEmail.email
            if (!email) {
                actions.setPasskeyError('Email is required')
                return
            }

            actions.setPasskeyRegistering(true)
            actions.setPasskeyError(null)

            try {
                // Step 1: Begin registration - get options from server
                const beginResponse = await api.create<RegistrationBeginResponse>(
                    'api/webauthn/signup-register/begin/',
                    { email }
                )

                if (beginResponse.already_registered) {
                    actions.setPasskeyRegistered(true)
                    actions.setSignupPanelAuthValue('password', '')
                    return
                }

                // Step 2: Create credential using SimpleWebAuthn
                const attestation = await startRegistration({
                    optionsJSON: {
                        rp: beginResponse.rp,
                        user: beginResponse.user,
                        challenge: beginResponse.challenge,
                        pubKeyCredParams: beginResponse.pubKeyCredParams as PublicKeyCredentialParameters[],
                        timeout: beginResponse.timeout,
                        excludeCredentials: beginResponse.excludeCredentials ?? [],
                        authenticatorSelection: beginResponse.authenticatorSelection as AuthenticatorSelectionCriteria,
                        attestation: beginResponse.attestation as AttestationConveyancePreference,
                    },
                })

                // Step 3: Complete registration - send attestation to server
                await api.create('api/webauthn/signup-register/complete/', attestation)

                actions.setPasskeyRegistered(true)
                actions.setSignupPanelAuthValue('password', '') // Clear password since we're using passkey
            } catch (e: any) {
                actions.setPasskeyError(getPasskeyErrorMessage(e, 'Failed to register passkey. Please try again.'))
            } finally {
                actions.setPasskeyRegistering(false)
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
                    actions.setSignupPanel1Values({ email })
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
