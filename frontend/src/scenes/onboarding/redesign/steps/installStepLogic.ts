import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { invitesDelegateCreate } from '~/generated/core/api'

import type { installStepLogicType } from './installStepLogicType'

const isValidEmail = (email: string): boolean => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())

/** Pull the most actionable message out of an API error (rate limit, DRF detail, or field errors). */
function extractErrorDetail(error: unknown, fallback: string): string {
    const err = (error ?? {}) as { status?: number; data?: unknown; message?: string }
    if (err.status === 429) {
        return "You've sent too many invitations recently. Please try again in a few minutes."
    }
    const data: unknown = err.data ?? error
    if (typeof data === 'string') {
        return data
    }
    if (data && typeof data === 'object') {
        const record = data as Record<string, unknown>
        if (typeof record.detail === 'string') {
            return record.detail
        }
        for (const value of Object.values(record)) {
            if (Array.isArray(value) && typeof value[0] === 'string') {
                return value[0]
            }
            if (typeof value === 'string') {
                return value
            }
        }
    }
    return err.message || fallback
}

/**
 * Drives the "delegate install to a developer" panel on the install step. Sends a single
 * admin-level delegation invite via `invitesDelegateCreate` and records that the inviter
 * delegated setup. Self-contained so the install step stays presentational.
 */
export const installStepLogic = kea<installStepLogicType>([
    path(['scenes', 'onboarding', 'redesign', 'steps', 'installStepLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganizationId']],
        actions: [userLogic, ['loadUser']],
    })),
    actions({
        setDelegateOpen: (delegateOpen: boolean) => ({ delegateOpen }),
        setDelegateEmail: (delegateEmail: string) => ({ delegateEmail }),
        submitDelegation: true,
        setIsSubmitting: (isSubmitting: boolean) => ({ isSubmitting }),
        delegationSent: true,
    }),
    reducers({
        delegateOpen: [false, { setDelegateOpen: (_, { delegateOpen }) => delegateOpen }],
        delegateEmail: ['', { setDelegateEmail: (_, { delegateEmail }) => delegateEmail }],
        isSubmitting: [false, { setIsSubmitting: (_, { isSubmitting }) => isSubmitting }],
        // Editing the email after a send lets the user delegate to someone else.
        sent: [false, { delegationSent: () => true, setDelegateEmail: () => false }],
    }),
    selectors({
        canSubmitDelegation: [
            (s) => [s.delegateEmail, s.isSubmitting],
            (delegateEmail, isSubmitting): boolean => !isSubmitting && isValidEmail(delegateEmail),
        ],
    }),
    listeners(({ actions, values }) => ({
        submitDelegation: async () => {
            // Re-entrant by default — guard against Enter-then-click double submits.
            if (values.isSubmitting || !isValidEmail(values.delegateEmail)) {
                return
            }
            const organizationId = values.currentOrganizationId
            if (!organizationId) {
                lemonToast.error("Couldn't find your current organization. Please refresh and try again.")
                return
            }
            const targetEmail = values.delegateEmail.trim()
            actions.setIsSubmitting(true)
            try {
                await invitesDelegateCreate(organizationId, {
                    target_email: targetEmail,
                    step_at_delegation: 'install',
                })
                lemonToast.success(`Invitation sent to ${targetEmail}`)
                actions.delegationSent()
                // Refresh delegation state so the rest of the app sees this org as delegated.
                actions.loadUser()
            } catch (error: unknown) {
                lemonToast.error(extractErrorDetail(error, "Couldn't send the invitation. Please try again."))
            } finally {
                actions.setIsSubmitting(false)
            }
        },
    })),
])
