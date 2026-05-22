import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { getRelativeNextPath } from 'lib/utils'
import type { PendingInvite } from 'scenes/authentication/signup/signupForm/signupLogic'

import type { confirmOrganizationLogicType } from './confirmOrganizationLogicType'

export interface ConfirmOrganizationFormValues {
    organization_name?: string
    first_name?: string
    role_at_organization?: string
    referral_source?: string
    referral_source_ai_prompt?: string
}

interface SignupEmailPrecheckResponse {
    email_exists: boolean
    code?: string
    detail?: string
    pending_invite?: PendingInvite | null
}

export const confirmOrganizationLogic = kea<confirmOrganizationLogicType>([
    path(['scenes', 'organization', 'confirmOrganizationLogic']),

    actions({
        setEmail: (email: string) => ({
            email,
        }),
        checkPendingInvite: (email: string) => ({ email }),
        setPendingInvite: (invite: PendingInvite | null) => ({ invite }),
        dismissPendingInvite: true,
        resendPendingInvite: (email: string) => ({ email }),
        setPendingInviteResent: (resent: boolean) => ({ resent }),
        setPendingInviteResending: (resending: boolean) => ({ resending }),
    }),

    reducers({
        email: [
            '',
            {
                setEmail: (_, { email }) => email,
            },
        ],
        pendingInvite: [
            null as PendingInvite | null,
            {
                setPendingInvite: (_, { invite }) => invite,
                dismissPendingInvite: () => null,
            },
        ],
        pendingInviteResent: [
            false,
            {
                setPendingInviteResent: (_, { resent }) => resent,
                setPendingInvite: () => false,
                dismissPendingInvite: () => false,
            },
        ],
        isPendingInviteResending: [
            false,
            {
                setPendingInviteResending: (_, { resending }) => resending,
            },
        ],
    }),

    selectors({
        loginUrl: [
            () => [router.selectors.searchParams],
            (searchParams: Record<string, string>) => {
                const nextParam = getRelativeNextPath(searchParams['next'], location)
                return nextParam ? `/login?next=${encodeURIComponent(nextParam)}` : '/login'
            },
        ],
    }),

    forms(() => ({
        confirmOrganization: {
            defaults: {} as ConfirmOrganizationFormValues,
            errors: ({ organization_name, first_name }) => ({
                first_name: !first_name ? 'Please enter your name' : undefined,
                organization_name: !organization_name ? 'Please enter your organization name' : undefined,
            }),

            submit: async (formValues) => {
                await api
                    .create('api/social_signup/', {
                        ...formValues,
                    })
                    .then(() => {
                        const nextUrl = getRelativeNextPath(new URLSearchParams(location.search).get('next'), location)

                        // this url is validated in getRelativeNextPath as either being relative or on the same origin
                        // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                        location.href = nextUrl || '/'
                    })
                    .catch((error: any) => {
                        console.error('error', error)
                        lemonToast.error(error.detail || 'Failed to create organization')
                    })
            },
        },
    })),

    listeners(({ actions }) => ({
        checkPendingInvite: async ({ email }, breakpoint) => {
            if (!email) {
                return
            }
            await breakpoint(100)
            try {
                const response = await api.create<SignupEmailPrecheckResponse>('api/signup/precheck', { email })
                breakpoint()
                actions.setPendingInvite(response.pending_invite ?? null)
            } catch {
                // The precheck is a soft enhancement — failing it should not block org creation.
                actions.setPendingInvite(null)
            }
        },
        resendPendingInvite: async ({ email }, breakpoint) => {
            actions.setPendingInviteResending(true)
            try {
                await api.create('api/signup/resend-invite', { email })
                breakpoint()
                actions.setPendingInviteResent(true)
            } catch {
                lemonToast.error('Could not resend the invite email. Please try again.')
            } finally {
                actions.setPendingInviteResending(false)
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/organization/confirm-creation': (_, { email, organization_name, first_name }) => {
            actions.setConfirmOrganizationValues({ organization_name, first_name })
            actions.setEmail(email ?? '')
            if (email) {
                actions.checkPendingInvite(email)
            }
        },
    })),
])
