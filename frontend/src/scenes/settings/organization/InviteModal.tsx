import './InviteModal.scss'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { isEmail, pluralize } from 'lib/utils'
import { organizationMembershipLevelIntegers } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { inviteLogic } from './inviteLogic'

/** Shuffled placeholder names */
const PLACEHOLDER_NAMES: string[] = [...Array(10).fill('Jane'), ...Array(10).fill('John'), 'Sonic'].sort(
    () => Math.random() - 0.5
)
export const MAX_INVITES_AT_ONCE = 20

export function EmailUnavailableMessage(): JSX.Element {
    return (
        <LemonBanner type="info" className="my-2">
            <>
                This PostHog instance isn't{' '}
                <Link to="https://posthog.com/docs/self-host/configure/email" target="_blank" targetBlankIcon>
                    configured&nbsp;to&nbsp;send&nbsp;emails&nbsp;
                </Link>
                .<br />
                Remember to <u>share the invite link</u> with each team member you invite.
            </>
        </LemonBanner>
    )
}

export function InviteRow({ index, isDeletable }: { index: number; isDeletable: boolean }): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % PLACEHOLDER_NAMES.length]

    const { invitesToSend } = useValues(inviteLogic)
    const { updateInviteAtIndex, inviteTeamMembers, deleteInviteAtIndex } = useActions(inviteLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    const allowedLevels = myMembershipLevel
        ? organizationMembershipLevelIntegers.filter((listLevel) => listLevel <= myMembershipLevel)
        : [OrganizationMembershipLevel.Member]

    const allowedLevelsOptions = allowedLevels.map((level) => ({
        value: level,
        label: OrganizationMembershipLevel[level],
    }))

    return (
        <div className="flex gap-2">
            <div className="flex-2">
                <LemonInput
                    placeholder={`${name.toLowerCase()}@posthog.com`}
                    type="email"
                    className={`error-on-blur${!invitesToSend[index]?.isValid ? ' errored' : ''}`}
                    onChange={(v) => {
                        let isValid = true
                        if (v && !isEmail(v)) {
                            isValid = false
                        }
                        updateInviteAtIndex({ target_email: v, isValid }, index)
                    }}
                    value={invitesToSend[index]?.target_email}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            inviteTeamMembers()
                        }
                    }}
                    autoFocus={index === 0}
                    data-attr="invite-email-input"
                />
            </div>
            {preflight?.email_service_available && (
                <div className="flex-1 flex gap-1 items-center justify-between">
                    <LemonInput
                        placeholder={name}
                        className="flex-1"
                        onChange={(v) => {
                            updateInviteAtIndex({ first_name: v }, index)
                        }}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                inviteTeamMembers()
                            }
                        }}
                    />
                </div>
            )}
            {allowedLevelsOptions.length > 1 && (
                <div className="flex-1 flex gap-1 items-center justify-between">
                    <LemonSelect
                        fullWidth
                        data-attr="invite-row-org-member-level"
                        options={allowedLevelsOptions}
                        value={invitesToSend[index].level || allowedLevels[0]}
                        onChange={(v) => {
                            updateInviteAtIndex({ level: v }, index)
                        }}
                    />
                </div>
            )}
            {!preflight?.email_service_available && (
                <div className="flex-1 flex gap-1 items-center justify-between">
                    <LemonButton
                        type="primary"
                        className="flex-1"
                        disabled={!isEmail(invitesToSend[index].target_email)}
                        onClick={() => {
                            inviteTeamMembers()
                        }}
                        fullWidth
                        center
                        data-attr="invite-generate-invite-link"
                    >
                        Submit
                    </LemonButton>
                </div>
            )}

            {isDeletable && (
                <LemonButton icon={<IconTrash />} status="danger" onClick={() => deleteInviteAtIndex(index)} />
            )}
        </div>
    )
}

export function InviteTeamMatesComponent(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, inviteContainsOwnerLevel } = useValues(inviteLogic)
    const { appendInviteRow, updateMessage, setIsInviteConfirmed } = useActions(inviteLogic)

    const areInvitesCreatable = invitesToSend.length + 1 < MAX_INVITES_AT_ONCE
    const areInvitesDeletable = invitesToSend.length > 1

    const { currentOrganization } = useValues(organizationLogic)

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    const allowedLevels = myMembershipLevel
        ? organizationMembershipLevelIntegers.filter((listLevel) => listLevel <= myMembershipLevel)
        : [OrganizationMembershipLevel.Member]

    const allowedLevelsOptions = allowedLevels.map((level) => ({
        value: level,
        label: OrganizationMembershipLevel[level],
    }))

    return (
        <>
            {preflight?.licensed_users_available === 0 && (
                <LemonBanner type="warning">
                    You've hit the limit of team members you can invite to your PostHog instance given your license.
                    Please contact <Link to="mailto:sales@posthog.com">sales@posthog.com</Link> to upgrade your license.
                </LemonBanner>
            )}
            <div className="space-y-2">
                <div className="flex gap-2">
                    <b className="flex-2">Email address</b>
                    {preflight?.email_service_available && <b className="flex-1">Name (optional)</b>}
                    {allowedLevelsOptions.length > 1 && <b className="flex-1">Level</b>}
                    {!preflight?.email_service_available && <b className="flex-1" />}
                    {areInvitesDeletable && <b className="w-12" />}
                </div>

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

            {inviteContainsOwnerLevel && (
                <div className="mt-4">
                    <b>Confirm owner-level invites</b>

                    <div className="mb-2">
                        At least one invite is for an owner level member. Please type <strong>send invites</strong> to
                        confirm that you wish to send these invites.
                    </div>
                    <LemonInput
                        type="text"
                        placeholder="send invites"
                        onChange={(value) => {
                            setIsInviteConfirmed(value.toLowerCase() === 'send invites')
                        }}
                    />
                </div>
            )}
        </>
    )
}

export function InviteModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, canSubmit } = useValues(inviteLogic)
    const { resetInviteRows, inviteTeamMembers } = useActions(inviteLogic)

    const validInvitesCount = invitesToSend.filter((invite) => invite.isValid && invite.target_email).length

    return (
        <div className="InviteModal">
            <LemonModal
                isOpen={isOpen}
                onClose={() => {
                    resetInviteRows()
                    onClose()
                }}
                width={800}
                title={<>Invite others to {user?.organization?.name || 'PostHog'}</>}
                description={
                    preflight?.email_service_available ? (
                        <p>
                            Invite others to your organization to collaborate together in PostHog. An invite is specific
                            to an email address and expires after 3 days. Name can be provided for the team member's
                            convenience.
                        </p>
                    ) : (
                        <p>
                            This PostHog instance isn't configured to send emails. In the meantime, you can generate a
                            link for each team member you want to invite. You can always invite others at a later time.{' '}
                            <strong>Make sure you share links with the organization members you want to invite.</strong>
                        </p>
                    )
                }
                footer={
                    <>
                        {!preflight?.email_service_available ? (
                            <LemonButton center type="secondary" onClick={onClose}>
                                Done
                            </LemonButton>
                        ) : (
                            <>
                                <LemonButton
                                    onClick={() => {
                                        resetInviteRows()
                                        onClose()
                                    }}
                                    type="secondary"
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    onClick={() => inviteTeamMembers()}
                                    type="primary"
                                    disabled={!canSubmit}
                                    data-attr="invite-team-member-submit"
                                >
                                    {validInvitesCount
                                        ? `Invite ${pluralize(validInvitesCount, 'team member')}`
                                        : 'Invite team members'}
                                </LemonButton>
                            </>
                        )}
                    </>
                }
            >
                <InviteTeamMatesComponent />
            </LemonModal>
        </div>
    )
}
