import { actions, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getRelativeNextPath } from 'lib/utils'

import type { confirmOrganizationLogicType } from './confirmOrganizationLogicType'

export interface ConfirmOrganizationFormValues {
    organization_name?: string
    first_name?: string
    role_at_organization?: string
    referral_source?: string
    referral_source_ai_prompt?: string
}

export const confirmOrganizationLogic = kea<confirmOrganizationLogicType>([
    path(['scenes', 'organization', 'confirmOrganizationLogic']),

    actions({
        setEmail: (email: string) => ({
            email,
        }),
        setShowNewOrgWarning: (show: boolean) => ({ show }),
        setChallengeRequired: (required: boolean) => ({ required }),
        setChallengeNonce: (nonce: string | null) => ({ nonce }),
        setTurnstileSiteKey: (siteKey: string | null) => ({ siteKey }),
        setTurnstileToken: (token: string | null) => ({ token }),
        resetChallenge: true,
    }),

    reducers({
        showNewOrgWarning: [
            false,
            {
                setShowNewOrgWarning: (_, { show }) => show,
            },
        ],
        email: [
            '',
            {
                setEmail: (_, { email }) => email,
            },
        ],
        challengeRequired: [
            false,
            {
                setChallengeRequired: (_, { required }) => required,
                resetChallenge: () => false,
            },
        ],
        challengeNonce: [
            null as string | null,
            {
                setChallengeNonce: (_, { nonce }) => nonce,
                resetChallenge: () => null,
            },
        ],
        turnstileSiteKey: [
            null as string | null,
            {
                setTurnstileSiteKey: (_, { siteKey }) => siteKey,
            },
        ],
        turnstileToken: [
            null as string | null,
            {
                setTurnstileToken: (_, { token }) => token,
                resetChallenge: () => null,
            },
        ],
    }),

    forms(({ actions, values }) => ({
        confirmOrganization: {
            defaults: {} as ConfirmOrganizationFormValues,
            errors: ({ organization_name, first_name }) => ({
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),

            submit: async (formValues) => {
                const submitData: Record<string, any> = { ...formValues }

                if (values.turnstileToken && values.challengeNonce) {
                    submitData.turnstile_token = values.turnstileToken
                    submitData.challenge_nonce = values.challengeNonce
                }

                await api
                    .create('api/social_signup/', submitData)
                    .then(() => {
                        const nextUrl = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)

                        // this url is validated in getRelativeNextPath as either being relative or on the same origin
                        // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                        location.href = nextUrl || '/'
                    })
                    .catch((error: any) => {
                        if (error.code === 'challenge_required') {
                            actions.setTurnstileToken(null)
                            actions.setChallengeNonce(error.data?.extra?.challenge_nonce)
                            actions.setTurnstileSiteKey(error.data?.extra?.turnstile_site_key)
                            actions.setChallengeRequired(true)
                            return
                        }

                        actions.resetChallenge()
                        console.error('error', error)
                        lemonToast.error(error.detail || 'Failed to create organization')
                    })
            },
        },
    })),

    listeners(({ actions, values }) => ({
        setTurnstileToken: ({ token }) => {
            if (token && values.challengeNonce) {
                actions.submitConfirmOrganization()
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/organization/confirm-creation': (_, { email, organization_name, first_name }) => {
            actions.setConfirmOrganizationValues({ organization_name, first_name })
            actions.setEmail(email)
        },
    })),
])
