import './InviteModal.scss'

import { useActions, useValues } from 'kea'

import { IconInfo, IconPlus, IconTrash } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSelect, LemonTextArea, Link, Tooltip } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { RestrictionScope } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { capitalizeFirstLetter, isEmail, pluralize } from 'lib/utils'
import { organizationMembershipLevelIntegers } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AvailableFeature } from '~/types'

import { GuestResourcePicker } from './GuestResourcePicker'
import { inviteLogic } from './inviteLogic'

/** Shuffled placeholder names */
const PLACEHOLDER_NAMES: string[] = [...Array(10).fill('Jane'), ...Array(10).fill('John'), 'Sonic'].sort(
    () => Math.random() - 0.5
)
export const MAX_INVITES_AT_ONCE = 20

export function EmailUnavailableForInvitesBanner(): JSX.Element {
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

export function ProjectAccessSelector({ inviteIndex }: { inviteIndex: number }): JSX.Element {
    const { invitesToSend, availableProjects, projectAccessControls } = useValues(inviteLogic)
    const {
        updateInviteAtIndex,
        addProjectAccess: addProjectAccessAction,
        removeProjectAccess: removeProjectAccessAction,
    } = useActions(inviteLogic)

    const invite = invitesToSend[inviteIndex]
    const selectedProjects = invite.private_project_access || []

    // Check if organization level is admin or owner (which will override project access)
    const isOrgLevelAdminOrOwner =
        invite.level === OrganizationMembershipLevel.Admin || invite.level === OrganizationMembershipLevel.Owner

    const availableProjectsToShow = availableProjects.filter(
        (project: any) => !selectedProjects.some((selected) => selected.id === project.id)
    )

    const addProjectAccess = (projectId: number, level: AccessControlLevel): void => {
        addProjectAccessAction(inviteIndex, projectId, level)
    }

    const removeProjectAccess = (projectId: number): void => {
        removeProjectAccessAction(inviteIndex, projectId)
    }

    const updateProjectAccess = (projectId: number, level: AccessControlLevel): void => {
        const newAccess = selectedProjects.map((access) => (access.id === projectId ? { ...access, level } : access))
        updateInviteAtIndex({ private_project_access: newAccess }, inviteIndex)
    }

    if (availableProjects.length === 0 && selectedProjects.length === 0) {
        return <></>
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <h4 className="text-sm font-medium mb-0">Project access</h4>
                <Tooltip
                    title={
                        <span>
                            Give this user access to specific projects. These access controls will be applied when the
                            user accepts the invite and joins the organization. Learn more about{' '}
                            <Link to="https://posthog.com/docs/settings/access-control" target="_blank">
                                access controls
                            </Link>{' '}
                            in our docs.
                        </span>
                    }
                >
                    <IconInfo className="text-muted-alt" />
                </Tooltip>
                {availableProjectsToShow.length > 0 && (
                    <LemonSelect
                        icon={<IconPlus />}
                        className="bg-bg-light"
                        placeholder="Add project"
                        options={availableProjectsToShow.map((project: any) => ({
                            value: project.id,
                            label: project.name,
                        }))}
                        onChange={(projectId) => {
                            if (projectId) {
                                addProjectAccess(Number(projectId), AccessControlLevel.Member)
                            }
                        }}
                    />
                )}
            </div>

            {isOrgLevelAdminOrOwner && selectedProjects.length > 0 && (
                <LemonBanner type="warning" className="text-xs">
                    This user will have{' '}
                    <span className="font-bold italic">{OrganizationMembershipLevel[invite.level].toLowerCase()}</span>{' '}
                    access on the organization level, which will override any project-specific access controls.
                </LemonBanner>
            )}

            {selectedProjects.length > 0 && (
                <div className="space-y-2">
                    {selectedProjects.map((access) => {
                        const project = availableProjects.find((p: any) => p.id === access.id)
                        if (!project) {
                            return null
                        }

                        const defaultLevel = projectAccessControls[project.id]?.access_level
                        const isLowerThanDefault = defaultLevel === 'admin' && access.level === 'member'

                        return (
                            <div key={access.id} className="space-y-2">
                                <div className="p-2 bg-bg-light rounded border">
                                    {isLowerThanDefault && (
                                        <div className="mb-2">
                                            <LemonBanner type="warning" className="text-xs">
                                                <strong>{project.name}</strong> has a default access level of{' '}
                                                <span className="font-bold italic">{defaultLevel}</span>. Since you
                                                selected <span className="font-bold italic">{access.level}</span> (which
                                                is lower), the user will actually get{' '}
                                                <span className="font-bold italic">{defaultLevel}</span> access.
                                            </LemonBanner>
                                        </div>
                                    )}
                                    <div className="flex items-center gap-2">
                                        <div className="flex-1">
                                            <span className="font-medium">{project.name}</span>{' '}
                                            {defaultLevel && <span>(default: {defaultLevel})</span>}
                                        </div>
                                        <LemonSelect
                                            className="bg-bg-light"
                                            size="small"
                                            options={[
                                                {
                                                    value: AccessControlLevel.Member,
                                                    label: capitalizeFirstLetter(AccessControlLevel.Member),
                                                },
                                                {
                                                    value: AccessControlLevel.Admin,
                                                    label: capitalizeFirstLetter(AccessControlLevel.Admin),
                                                },
                                            ]}
                                            value={access.level}
                                            onChange={(level) => {
                                                if (level) {
                                                    updateProjectAccess(access.id, level)
                                                }
                                            }}
                                        />
                                        <LemonButton
                                            size="small"
                                            icon={<IconTrash />}
                                            status="danger"
                                            onClick={() => removeProjectAccess(access.id)}
                                        />
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

// Sentinel value for the "Guest" entry in the organization-level dropdown. Selecting it
// flips the whole invite form into guest mode (same effect as the Invite-as-guest checkbox).
const GUEST_LEVEL_OPTION = 'guest' as const
type OrgLevelValue = number | typeof GUEST_LEVEL_OPTION

export function InviteRow({
    index,
    isDeletable,
    hideProjectAccessSelector = false,
    hideOrgLevelSelector = false,
}: {
    index: number
    isDeletable: boolean
    hideProjectAccessSelector?: boolean
    hideOrgLevelSelector?: boolean
}): JSX.Element {
    const name = PLACEHOLDER_NAMES[index % PLACEHOLDER_NAMES.length]

    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPermissions = hasAvailableFeature(AvailableFeature.ADVANCED_PERMISSIONS)
    const hasAccessControl = hasAvailableFeature(AvailableFeature.ACCESS_CONTROL)
    const guestModeEnabled = useFeatureFlag('GUEST_MODE')

    const { invitesToSend, isGuestInvite } = useValues(inviteLogic)
    const inviteActions = useActions(inviteLogic)
    const { updateInviteAtIndex, inviteTeamMembers, deleteInviteAtIndex, setIsGuestInvite } = inviteActions
    const { preflight } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    const allowedLevels = myMembershipLevel
        ? organizationMembershipLevelIntegers.filter((listLevel) => listLevel <= myMembershipLevel)
        : [OrganizationMembershipLevel.Member]

    const hasMultipleInvites = invitesToSend.length > 1
    // Guest invites require admin+ on the backend, which is exactly when `allowedLevels`
    // has more than one option (the current user can assign at least one level below their own).
    // Gating the Guest option on this keeps it out of the dropdown for non-admin inviters
    // who couldn't create a guest invite anyway.
    const canShowGuestLevel = guestModeEnabled && hasAccessControl && allowedLevels.length > 1

    // Guest sits at the top of the dropdown but Member remains the default (the value prop
    // resolves to Member when invitesToSend[index].level is unset — `allowedLevels[0]` is Member
    // because `organizationMembershipLevelIntegers` starts at Member).
    const allowedLevelsOptions: { value: OrgLevelValue; label: string; disabledReason?: string }[] = [
        ...(canShowGuestLevel
            ? [
                  {
                      value: GUEST_LEVEL_OPTION,
                      label: 'Guest',
                      disabledReason: hasMultipleInvites
                          ? 'Guest invites go out one at a time. Remove extra rows to invite as guest.'
                          : undefined,
                  },
              ]
            : []),
        ...allowedLevels.map((level) => ({
            value: level as OrgLevelValue,
            label: OrganizationMembershipLevel[level],
        })),
    ]

    return (
        <div className="space-y-4 bg-surface-secondary py-4 px-4 rounded-md">
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
                            value={invitesToSend[index].first_name}
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
                {allowedLevelsOptions.length > 1 && !hideOrgLevelSelector && (
                    <div className="flex-1 flex gap-1 items-center justify-between">
                        <LemonSelect<OrgLevelValue>
                            className="bg-bg-light"
                            fullWidth
                            data-attr="invite-row-org-member-level"
                            options={allowedLevelsOptions}
                            value={isGuestInvite ? GUEST_LEVEL_OPTION : invitesToSend[index].level || allowedLevels[0]}
                            onChange={(v) => {
                                if (v === GUEST_LEVEL_OPTION) {
                                    setIsGuestInvite(true)
                                    return
                                }
                                if (typeof v === 'number') {
                                    // Switching away from Guest: null out guest-only state so we
                                    // don't ship a member invite with attached grants. Safe to
                                    // call unconditionally — a no-op when we weren't in guest mode.
                                    inviteActions.resetGuestState()
                                    updateInviteAtIndex({ level: v }, index)
                                }
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

            {hasAdvancedPermissions && !hideProjectAccessSelector && <ProjectAccessSelector inviteIndex={index} />}
        </div>
    )
}

export function InviteTeamMatesComponent({
    hideProjectAccessSelector = false,
}: {
    hideProjectAccessSelector?: boolean
}): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, inviteContainsOwnerLevel, isGuestInvite, bypassSsoEnforcement } = useValues(inviteLogic)
    const { appendInviteRow, updateMessage, setIsInviteConfirmed, setBypassSsoEnforcement } = useActions(inviteLogic)

    const { currentOrganization } = useValues(organizationLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAccessControl = hasAvailableFeature(AvailableFeature.ACCESS_CONTROL)
    const guestModeEnabled = useFeatureFlag('GUEST_MODE')

    const areInvitesCreatable = invitesToSend.length + 1 < MAX_INVITES_AT_ONCE && !isGuestInvite
    const areInvitesDeletable = invitesToSend.length > 1

    const myMembershipLevel = currentOrganization ? currentOrganization.membership_level : null

    const allowedLevels = myMembershipLevel
        ? organizationMembershipLevelIntegers.filter((listLevel) => listLevel <= myMembershipLevel)
        : [OrganizationMembershipLevel.Member]

    const allowedLevelsOptions = allowedLevels.map((level) => ({
        value: level,
        label: OrganizationMembershipLevel[level],
    }))

    // Only offer SSO bypass if the org actually enforces SSO; otherwise the toggle is meaningless.
    const orgHasSsoEnforced = !!(currentOrganization as any)?.sso_enforcement

    return (
        <>
            {preflight?.licensed_users_available === 0 && (
                <LemonBanner type="warning">
                    You've hit the limit of team members you can invite to your PostHog instance given your license.
                    Please contact <Link to="mailto:sales@posthog.com">sales@posthog.com</Link> to upgrade your license.
                </LemonBanner>
            )}
            <div className="deprecated-space-y-4">
                <div className="flex gap-2">
                    <b className="flex-2">Email address</b>
                    {preflight?.email_service_available && <b className="flex-1">Name (optional)</b>}
                    {allowedLevelsOptions.length > 1 && <b className="flex-1">Organization level</b>}
                    {!preflight?.email_service_available && <b className="flex-1" />}
                    {areInvitesDeletable && <b className="w-12" />}
                </div>

                {invitesToSend.map((_, index) => (
                    <InviteRow
                        hideProjectAccessSelector={hideProjectAccessSelector || isGuestInvite}
                        index={index}
                        key={index.toString()}
                        isDeletable={areInvitesDeletable}
                    />
                ))}

                <div className="mt-2 flex justify-end">
                    {areInvitesCreatable && (
                        <LemonButton type="secondary" icon={<IconPlus />} onClick={appendInviteRow}>
                            Add
                        </LemonButton>
                    )}
                </div>
            </div>

            {guestModeEnabled && hasAccessControl && isGuestInvite && (
                <div className="mt-4 p-3 border rounded-md space-y-3" data-attr="guest-invite-block">
                    <div className="flex items-center gap-2">
                        <b>Guest access</b>
                        <Tooltip title="Guests are external collaborators with read-only access to dashboards, insights, or notebooks you select. They don't appear in member pickers, filters, or @ mentions.">
                            <IconInfo className="text-muted-alt" />
                        </Tooltip>
                    </div>
                    <GuestResourcePicker />
                    {orgHasSsoEnforced && (
                        <div className="space-y-2">
                            <LemonCheckbox
                                checked={bypassSsoEnforcement}
                                onChange={setBypassSsoEnforcement}
                                label="Bypass SSO enforcement for this guest"
                                data-attr="guest-invite-bypass-sso"
                            />
                            {bypassSsoEnforcement && (
                                <LemonBanner type="warning">
                                    I understand this lets the guest authenticate with email + password even though our
                                    organization enforces SSO.
                                </LemonBanner>
                            )}
                        </div>
                    )}
                </div>
            )}

            {preflight?.email_service_available && !isGuestInvite && (
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

            {inviteContainsOwnerLevel && !isGuestInvite && (
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
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { invitesToSend, canSubmit, isInviting } = useValues(inviteLogic)
    const { resetInviteRows, inviteTeamMembers } = useActions(inviteLogic)

    const validInvitesCount = invitesToSend.filter((invite) => invite.isValid && invite.target_email).length

    const minAdminRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    const userCannotInvite = minAdminRestrictionReason && !currentOrganization?.members_can_invite

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
                                    disabled={isInviting}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    onClick={() => inviteTeamMembers()}
                                    type="primary"
                                    loading={isInviting}
                                    disabledReason={
                                        userCannotInvite
                                            ? "You don't have permissions to invite others."
                                            : !canSubmit
                                              ? 'Please fill out all fields'
                                              : undefined
                                    }
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
