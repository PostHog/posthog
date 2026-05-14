import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { invitesDelegateCreate } from '~/generated/core/api'
import { UserType } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import type { onboardingExitLogicType } from './onboardingExitLogicType'

const isValidEmail = (email: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())

type ApiErrorLike = {
    status?: number
    data?: unknown
    message?: string
}

function asApiError(error: unknown): ApiErrorLike {
    return (error ?? {}) as ApiErrorLike
}

/** Pull the most actionable detail out of an API error (DRF field errors, validation messages, or generic detail). */
function extractErrorDetail(error: unknown, fallback: string): string {
    const err = asApiError(error)
    // DRF returns 429 with a machine-readable "Expected available in N seconds" string.
    // Surface a friendlier message instead of leaking the raw retry-after seconds to the user.
    if (err.status === 429) {
        return "You've sent too many invitations recently. Please try again in a few minutes."
    }
    const data: unknown = err.data ?? error
    if (typeof data === 'string') {
        return data
    }
    if (data && typeof data === 'object') {
        const dataRecord = data as Record<string, unknown>
        const detail = dataRecord.detail
        if (typeof detail === 'string') {
            return detail
        }
        // DRF validation errors shape: { field: ["msg1", ...], ... }
        for (const key of Object.keys(dataRecord)) {
            const val = dataRecord[key]
            if (Array.isArray(val) && val.length && typeof val[0] === 'string') {
                return val[0]
            }
            if (typeof val === 'string') {
                return val
            }
        }
    }
    return err.message || fallback
}

export const onboardingExitLogic = kea<onboardingExitLogicType>([
    path(['scenes', 'onboarding', 'onboardingExitLogic']),
    connect(() => ({
        values: [
            onboardingLogic,
            ['stepKey', 'onCompleteOnboardingRedirectUrl'],
            organizationLogic,
            ['currentOrganizationId'],
        ],
        actions: [userLogic, ['loadUser', 'loadUserSuccess']],
    })),
    actions({
        openExitModal: true,
        closeExitModal: true,
        setTargetEmail: (targetEmail: string) => ({ targetEmail }),
        setMessage: (message: string) => ({ message }),
        submitDelegation: true,
        setIsSubmitting: (isSubmitting: boolean) => ({ isSubmitting }),
        captureOrgIdAtOpen: (orgId: string | null) => ({ orgId }),
    }),
    reducers({
        isExitModalOpen: [
            false,
            {
                openExitModal: () => true,
                closeExitModal: () => false,
            },
        ],
        targetEmail: [
            '',
            {
                setTargetEmail: (_, { targetEmail }) => targetEmail,
                closeExitModal: () => '',
            },
        ],
        message: [
            '',
            {
                setMessage: (_, { message }) => message,
                closeExitModal: () => '',
            },
        ],
        isSubmitting: [
            false,
            {
                setIsSubmitting: (_, { isSubmitting }) => isSubmitting,
                closeExitModal: () => false,
            },
        ],
        // Pin the org id captured when the modal opened so we submit against the same org
        // even if the user switches orgs in another tab while this modal is open.
        orgIdAtOpen: [
            null as string | null,
            {
                captureOrgIdAtOpen: (_, { orgId }) => orgId,
                closeExitModal: () => null,
            },
        ],
    }),
    selectors({
        canSubmitDelegation: [(s) => [s.targetEmail], (targetEmail: string) => isValidEmail(targetEmail)],
    }),
    listeners(({ actions, values }) => ({
        openExitModal: () => {
            // Frontend-only event (no backend counterpart); the delegation success event is fired from the backend.
            posthog.capture('onboarding exit modal opened', { step_at_open: values.stepKey || null })
            // Snapshot the org so a mid-modal org switch in another tab can't redirect the
            // submission to the wrong org.
            actions.captureOrgIdAtOpen(values.currentOrganizationId ?? null)
        },
        submitDelegation: async () => {
            // Guard against double-submit from Enter-Enter or rapid button double-click. The
            // listener is re-entrant by default — a second dispatch would fire another POST
            // before the first settles.
            if (values.isSubmitting) {
                return
            }
            if (!values.canSubmitDelegation) {
                return
            }
            const orgId = values.orgIdAtOpen ?? values.currentOrganizationId
            if (!orgId) {
                lemonToast.error("Couldn't find your current organization. Please refresh and try again.")
                return
            }
            // Fail-closed if the user switched orgs in another tab while this modal was open.
            // Submitting against the previous org would create the invite under the wrong tenant.
            if (
                values.orgIdAtOpen &&
                values.currentOrganizationId &&
                values.orgIdAtOpen !== values.currentOrganizationId
            ) {
                lemonToast.error(
                    'Your active organization changed while this dialog was open. Please reopen and try again.'
                )
                actions.closeExitModal()
                return
            }
            actions.setIsSubmitting(true)
            let delegationCommitted = false
            try {
                await invitesDelegateCreate(orgId, {
                    target_email: values.targetEmail.trim(),
                    message: values.message.trim(),
                    step_at_delegation: values.stepKey || '',
                })
                delegationCommitted = true
                lemonToast.success(`Invitation sent to ${values.targetEmail.trim()}`)

                // Seed the freshest user into userLogic BEFORE navigating, otherwise sceneLogic's
                // onboarding-redirect check reads stale state and bounces us straight back to /onboarding.
                // We hit `/api/users/@me/` — the same endpoint `loadUser` uses — so the response shape
                // matches what the rest of the app (and `isOnboardingRedirectSuppressed`) expects, and
                // `onboarding_skipped_at` reliably lands in state before the scene change fires.
                try {
                    const freshUser = await api.get<UserType>('api/users/@me/')
                    actions.loadUserSuccess(freshUser)
                } catch {
                    // If the refresh fails, trigger a background load so the app eventually converges.
                    actions.loadUser()
                }

                actions.closeExitModal()
                // Always redirect on success. Even if the fresh-user fetch didn't return hydrated
                // delegation state (eventual consistency, network glitch), sceneLogic's suppression
                // check will catch up once `loadUser` populates state — leaving the user on
                // `/onboarding/products` after a green toast is a worse UX than the brief redirect race.
                // `replace` (not `push`) so the `/onboarding/…` URL is dropped from history.
                router.actions.replace(values.onCompleteOnboardingRedirectUrl)
            } catch (error: unknown) {
                if (delegationCommitted) {
                    // POST succeeded but a follow-up step failed — don't show a scary error
                    // that would make the user re-submit into `existing_invite`.
                    actions.closeExitModal()
                    return
                }
                lemonToast.error(extractErrorDetail(error, "Couldn't send the invitation. Please try again."))
            } finally {
                actions.setIsSubmitting(false)
            }
        },
    })),
])
