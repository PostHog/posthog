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

/** Pull the most actionable detail out of an API error (DRF field errors, validation messages, or generic detail). */
function extractErrorDetail(error: any, fallback: string): string {
    if (!error) {
        return fallback
    }
    const data = error.data ?? error
    if (typeof data === 'string') {
        return data
    }
    if (data?.detail && typeof data.detail === 'string') {
        return data.detail
    }
    // DRF validation errors shape: { field: ["msg1", ...], ... }
    if (data && typeof data === 'object') {
        for (const key of Object.keys(data)) {
            const val = (data as any)[key]
            if (Array.isArray(val) && val.length && typeof val[0] === 'string') {
                return val[0]
            }
            if (typeof val === 'string') {
                return val
            }
        }
    }
    return error.message || fallback
}

export const onboardingExitLogic = kea<onboardingExitLogicType>([
    path(['scenes', 'onboarding', 'onboardingExitLogic']),
    connect(() => ({
        values: [onboardingLogic, ['stepKey', 'onCompleteOnboardingRedirectUrl']],
        actions: [userLogic, ['loadUser', 'loadUserSuccess']],
    })),
    actions({
        openExitModal: true,
        closeExitModal: true,
        setTargetEmail: (targetEmail: string) => ({ targetEmail }),
        setMessage: (message: string) => ({ message }),
        submitDelegation: true,
        setIsSubmitting: (isSubmitting: boolean) => ({ isSubmitting }),
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
    }),
    selectors({
        canSubmitDelegation: [(s) => [s.targetEmail], (targetEmail) => isValidEmail(targetEmail)],
    }),
    listeners(({ actions, values }) => ({
        openExitModal: () => {
            // Frontend-only event (no backend counterpart); the delegation success event is fired from the backend.
            posthog.capture('onboarding exit modal opened', { step_at_open: values.stepKey || null })
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
            const orgId = organizationLogic.values.currentOrganizationId
            if (!orgId) {
                lemonToast.error("Couldn't find your current organization. Please refresh and try again.")
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
                let freshUserLoaded = false
                try {
                    const freshUser = await api.get<UserType>('api/users/@me/')
                    actions.loadUserSuccess(freshUser)
                    freshUserLoaded = Boolean(freshUser?.onboarding_delegated_to_invite)
                } catch {
                    // If the refresh fails, trigger a background load so the app eventually converges.
                    actions.loadUser()
                }

                actions.closeExitModal()
                // If the fresh-user fetch didn't return hydrated delegation state, don't race
                // sceneLogic's redirect back into /onboarding — stay on the onboarding route
                // and let the background loadUser populate state. The scene will transition
                // to the waiting screen automatically once the user object updates.
                if (freshUserLoaded) {
                    // Match the normal post-onboarding redirect: product-specific landing page if a
                    // product was selected, otherwise the default home. `replace` (not `push`) so the
                    // `/onboarding/…` URL is dropped from history.
                    router.actions.replace(values.onCompleteOnboardingRedirectUrl)
                }
            } catch (error: any) {
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
