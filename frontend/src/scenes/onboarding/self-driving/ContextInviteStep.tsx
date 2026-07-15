import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteTeamMatesComponent } from 'scenes/settings/organization/InviteModal'

/**
 * Body of the "Invite your team" step in the context-first onboarding flow.
 *
 * Reuses the real bulk-invite UI (`InviteTeamMatesComponent`) and logic (`inviteLogic`) so teammates
 * can be invited by email inline, no redirect to settings. Navigation (Back/Continue/Skip) is owned
 * by the parent shell; this renders body content only.
 */
export function ContextInviteStep(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, canSubmit, isInviting, inviteContainsOwnerLevel } = useValues(inviteLogic)
    const { inviteTeamMembers } = useActions(inviteLogic)

    const emailServiceAvailable = !!preflight?.email_service_available
    const hasFilledEmail = invitesToSend.some(({ target_email }) => !!target_email)
    const hasInvalidEmail = invitesToSend.some(({ isValid }) => !isValid)

    const sendDisabledReason = hasInvalidEmail
        ? 'Enter a valid email address'
        : inviteContainsOwnerLevel && !canSubmit
          ? 'Type "send invites" to confirm inviting owners'
          : !canSubmit
            ? 'Fill out all fields first'
            : undefined

    return (
        <div className="flex flex-col gap-4">
            <p className="text-sm text-muted m-0">
                PostHog gets better with the people who know the product. Bring your teammates in so they can steer the
                agents too.
            </p>

            {/* Reuses the real invite rows + logic: email, optional name, org level, add/remove. */}
            <InviteTeamMatesComponent hideProjectAccessSelector />

            {/* Only email-based invites get a dedicated send action; without an email service each row
                generates its own invite link via the component's per-row submit button. */}
            {emailServiceAvailable && (
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        icon={<IconCheckCircle />}
                        onClick={() => inviteTeamMembers()}
                        loading={isInviting}
                        disabledReason={!hasFilledEmail ? 'Add a teammate to invite' : sendDisabledReason}
                        data-attr="context-onboarding-send-invites"
                    >
                        Send invites
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
