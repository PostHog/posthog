import { LemonBanner, LemonButton, LemonDialog, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PhonePairHogs } from 'lib/components/hedgehogs'
import { IconDelete, IconPlus } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { InviteRow, MAX_INVITES_AT_ONCE } from 'scenes/settings/organization/InviteModal'
import { teamLogic } from 'scenes/teamLogic'

import { OrganizationInviteType } from '~/types'

import { OnboardingStepKey } from './onboardingLogic'
import { OnboardingStep } from './OnboardingStep'

export const OnboardingInviteTeammates = ({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element => {
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, invites } = useValues(inviteLogic)
    const { appendInviteRow, deleteInvite, updateMessage } = useActions(inviteLogic)

    const { currentTeam } = useValues(teamLogic)
    const completed_onboarding_products = Object.keys(currentTeam?.has_completed_onboarding_for || {})
    const productAnalyticsOnboarded = completed_onboarding_products.includes('product_analytics')
    const surveysOnboarded = completed_onboarding_products.includes('surveys')
    const sessionReplayOnboarded = completed_onboarding_products.includes('session_replay')

    const invitesReversed = invites.slice().reverse()
    const areInvitesCreatable = invitesToSend.length + 1 < MAX_INVITES_AT_ONCE
    const areInvitesDeletable = invitesToSend.length > 1

    return (
        <OnboardingStep title={`PostHog is better with teammates`} stepKey={stepKey}>
            <div className="flex items-center py-8 gap-8 mx-16">
                <span>
                    Invite your teammates so you can {productAnalyticsOnboarded && 'share your dashboard insights'}
                    {surveysOnboarded &&
                        `${productAnalyticsOnboarded ? ' and ' : ''}review your survey results together`}
                    {sessionReplayOnboarded &&
                        `${
                            surveysOnboarded || productAnalyticsOnboarded ? 'and' : ''
                        } have a session replay watch party`}
                    {!(productAnalyticsOnboarded || surveysOnboarded || sessionReplayOnboarded) &&
                        'supercharge your analytics experience'}
                    !
                </span>
                <PhonePairHogs height={120} width={288} />
            </div>
            {preflight?.email_service_available ? (
                <p>Enter their email below and we'll send them a custom invite link. Invites expire after 3 days.</p>
            ) : (
                <p>
                    This PostHog instance isn't configured to send emails. In the meantime, enter your teammates' emails
                    below to generate their custom invite links.{' '}
                    <strong>You'll need to share the links with your project members manually</strong>. You can invite
                    more people later.
                </p>
            )}
            {preflight?.licensed_users_available === 0 && (
                <LemonBanner type="warning">
                    You've hit the limit of team members you can invite to your PostHog instance given your license.
                    Please contact <Link to="mailto:sales@posthog.com">sales@posthog.com</Link> to upgrade your license.
                </LemonBanner>
            )}
            <div className="space-y-2">
                <div className="flex gap-2">
                    <b className="flex-1">Email address</b>
                    <b className="flex-1">{preflight?.email_service_available ? 'Name (optional)' : 'Invite link'}</b>
                </div>

                {invitesReversed.map((invite: OrganizationInviteType) => {
                    return (
                        <div className="flex gap-2 items-start" key={invite.id}>
                            <div className="flex-1">
                                <div className="flex-1 rounded border p-2">{invite.target_email} </div>
                            </div>

                            <div className="flex-1 flex gap-2 overflow-hidden">
                                {invite.is_expired ? (
                                    <b>Expired – please recreate</b>
                                ) : (
                                    <>
                                        {preflight?.email_service_available ? (
                                            <div className="flex-1 border rounded p-2"> {invite.first_name} </div>
                                        ) : (
                                            <CopyToClipboardInline
                                                data-attr="invite-link"
                                                explicitValue={new URL(`/signup/${invite.id}`, document.baseURI).href}
                                                description="invite link"
                                                style={{
                                                    color: 'var(--primary)',
                                                    background: 'var(--side)',
                                                    borderRadius: 4,
                                                    padding: '0.5rem',
                                                }}
                                            >
                                                <div className="InviteModal__share_link">
                                                    {new URL(`/signup/${invite.id}`, document.baseURI).href}
                                                </div>
                                            </CopyToClipboardInline>
                                        )}
                                    </>
                                )}
                                <LemonButton
                                    title="Cancel the invite"
                                    data-attr="invite-delete"
                                    icon={<IconDelete />}
                                    status="danger"
                                    onClick={() => {
                                        invite.is_expired
                                            ? deleteInvite(invite)
                                            : LemonDialog.open({
                                                  title: `Do you want to cancel the invite for ${invite.target_email}?`,
                                                  primaryButton: {
                                                      children: 'Yes, cancel invite',
                                                      status: 'danger',
                                                      onClick: () => deleteInvite(invite),
                                                  },
                                                  secondaryButton: {
                                                      children: 'No, keep invite',
                                                  },
                                              })
                                    }}
                                />
                            </div>
                        </div>
                    )
                })}

                {invitesToSend.map((_, index) => (
                    <InviteRow index={index} key={index.toString()} isDeletable={areInvitesDeletable} />
                ))}

                <div className="mt-2">
                    {areInvitesCreatable && (
                        <LemonButton type="secondary" icon={<IconPlus />} onClick={appendInviteRow} fullWidth center>
                            Add email address
                        </LemonButton>
                    )}
                </div>
            </div>
            {preflight?.email_service_available && (
                <div className="mt-4">
                    <div className="mb-2">
                        <b>Message (optional)</b>
                    </div>
                    <LemonTextArea
                        data-attr="invite-optional-message"
                        placeholder="Tell your teammates why you're inviting them to PostHog"
                        onChange={(e) => updateMessage(e)}
                    />
                </div>
            )}
        </OnboardingStep>
    )
}
