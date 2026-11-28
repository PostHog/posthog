import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    AvatarGroup,
    Badge,
    Button,
    DataTable,
    Heading,
    InputGroup,
    InputGroupInput,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { capitalizeFirstLetter, fullName, fullNameOrEmail } from 'lib/utils/strings'
import { twoFactorLogic } from 'scenes/authentication/two-factor-setup/twoFactorLogic'
import { membersExportLogic } from 'scenes/organization/membersExportLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'
import { AvailableFeature, OrganizationMemberType } from '~/types'

import { MemberOffboardingModal } from './MemberOffboardingModal'
import { accessibleProjects } from './memberProjectAccess'
import { memberProjectAccessLogic } from './memberProjectAccessLogic'
import { QuillMemberActionsMenu } from './QuillMemberActionsMenu'
import { QuillMemberProjectAccessCell } from './QuillMemberProjectAccessCell'
import { QuillMemberProjectAccessDialog } from './QuillMemberProjectAccessDialog'

const MEMBERS_PER_PAGE = 50

export function QuillMembers(): JSX.Element | null {
    const { filteredMembers, members, membersLoading, search } = useValues(membersLogic)
    const { projectAccess } = useValues(memberProjectAccessLogic)
    const { downloadMembersListDisabledReason } = useValues(membersExportLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { setSearch } = useActions(membersLogic)
    const { downloadMembersList } = useActions(membersExportLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { openTwoFactorSetupModal } = useActions(twoFactorLogic)

    const adminRestrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const hasHiddenMembers =
        currentOrganization?.members_can_see_org_members === false &&
        !!adminRestrictionReason &&
        !!members?.length &&
        members.length < currentOrganization.member_count

    // Highest level first, matching the default sort of the members table
    const sortedMembers = useMemo(
        () => [...(filteredMembers ?? [])].sort((a, b) => b.level - a.level),
        [filteredMembers]
    )

    if (!user) {
        return null
    }

    const columns: ColumnDef<OrganizationMemberType>[] = [
        {
            id: 'user_profile_picture',
            header: '',
            enableSorting: false,
            cell: ({ row }) => <QuillPersonAvatar name={fullName(row.original.user)} email={row.original.user.email} />,
        },
        {
            id: 'user_name',
            header: 'Member',
            meta: { expand: true },
            accessorFn: (member) => fullNameOrEmail(member.user),
            sortingFn: (a, b) => fullNameOrEmail(a.original.user).localeCompare(fullNameOrEmail(b.original.user)),
            cell: ({ row }) => {
                const member = row.original

                return (
                    <div className="flex flex-col items-start gap-0.5">
                        <Text size="xs" weight="medium" render={<span />} className="m-0 ph-no-capture">
                            {member.user.uuid == user.uuid
                                ? `${fullNameOrEmail(member.user)} (you)`
                                : fullNameOrEmail(member.user)}
                        </Text>
                        {fullName(member.user) && (
                            <Text size="xs" variant="muted" render={<span />} className="m-0 ph-no-capture">
                                {member.user.email}
                            </Text>
                        )}
                        {!member.user.is_email_verified &&
                            !member.has_social_auth &&
                            preflight?.email_service_available && (
                                <Badge variant="warning" data-attr="pending-email-verification">
                                    pending email verification
                                </Badge>
                            )}
                    </div>
                )
            },
        },
        {
            id: 'level',
            header: 'Level',
            accessorFn: (member) => member.level,
            cell: ({ row }) => (
                <Badge data-attr="membership-level">
                    {capitalizeFirstLetter(
                        membershipLevelToName.get(row.original.level) ?? `unknown (${row.original.level})`
                    )}
                </Badge>
            ),
        },
        {
            id: 'project_access',
            header: 'Project access',
            accessorFn: (member) => accessibleProjects(projectAccess?.[member.id] ?? []).length,
            cell: ({ row }) => <QuillMemberProjectAccessCell member={row.original} />,
        },
        {
            id: 'is_2fa_enabled',
            header: '2FA',
            accessorFn: (member) => (member.is_2fa_enabled ? 1 : 0),
            cell: ({ row }) => {
                const member = row.original
                const canSetUp = member.user.uuid == user.uuid && !member.is_2fa_enabled
                const badge = (
                    <Badge data-attr="2fa-enabled" variant={member.is_2fa_enabled ? 'success' : 'warning'}>
                        {member.is_2fa_enabled ? '2FA enabled' : '2FA not enabled'}
                    </Badge>
                )

                if (!canSetUp) {
                    return badge
                }

                return (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    className="cursor-pointer"
                                    onClick={() => openTwoFactorSetupModal()}
                                />
                            }
                        >
                            {badge}
                        </TooltipTrigger>
                        <TooltipContent>Click to setup 2FA for your account</TooltipContent>
                    </Tooltip>
                )
            },
        },
        {
            id: 'joined_at',
            header: 'Joined',
            accessorFn: (member) => member.joined_at,
            cell: ({ row }) => (
                <Text size="xs" render={<span />} className="m-0 whitespace-nowrap">
                    <TZLabel time={row.original.joined_at} />
                </Text>
            ),
        },
        {
            id: 'last_login',
            header: 'Last Logged In',
            accessorFn: (member) => new Date(member.last_login ?? 0).getTime(),
            cell: ({ row }) => (
                <Text size="xs" render={<span />} className="m-0 whitespace-nowrap">
                    {row.original.last_login ? <TZLabel time={row.original.last_login} /> : 'Never'}
                </Text>
            ),
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => <QuillMemberActionsMenu member={row.original} />,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2 justify-between items-center">
                <InputGroup size="sm" className="flex-1 basis-72 max-w-full">
                    <InputGroupInput
                        type="search"
                        placeholder="Search for members"
                        aria-label="Search for members"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                    />
                </InputGroup>
                {!adminRestrictionReason && (
                    <Button
                        variant="outline"
                        onClick={downloadMembersList}
                        disabledReason={downloadMembersListDisabledReason}
                        data-attr="org-members-download-csv"
                    >
                        Download members list
                    </Button>
                )}
            </div>

            <QuillMemberProjectAccessDialog />
            <MemberOffboardingModal />

            {membersLoading && !members?.length ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                </div>
            ) : (
                <div className="flex flex-col gap-2" data-attr="org-members-table">
                    <DataTable
                        columns={columns}
                        data={sortedMembers}
                        fullWidth
                        getRowId={(member) => member.id}
                        pageSize={MEMBERS_PER_PAGE}
                    />
                    {hasHiddenMembers && (
                        <div className="flex flex-wrap items-center gap-2 px-3">
                            <AvatarGroup stacked size="sm">
                                {[0, 1, 2].map((index) => (
                                    <Avatar key={index}>
                                        <AvatarFallback>?</AvatarFallback>
                                    </Avatar>
                                ))}
                            </AvatarGroup>
                            <Text size="xs" variant="muted" render={<span />} className="m-0">
                                Other organization members
                            </Text>
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={<Button size="icon-xs" aria-label="Why some members are hidden" />}
                                >
                                    <IconInfo />
                                </TooltipTrigger>
                                <TooltipContent>
                                    Your organization only shows the full member list to admins.
                                </TooltipContent>
                            </Tooltip>
                        </div>
                    )}
                </div>
            )}

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Two-factor authentication
                </Heading>
                <PayGateMini
                    feature={AvailableFeature.TWOFA_ENFORCEMENT}
                    featureDetail="organization-members-two-factor-authentication"
                >
                    <div className="flex flex-col gap-2">
                        <Text size="xs" render={<p className="m-0" />}>
                            Require all organization members to use two-factor authentication.
                        </Text>
                        <QuillSettingSwitch
                            label="Enforce 2FA"
                            checked={!!currentOrganization?.enforce_2fa}
                            onCheckedChange={(enforce_2fa) => updateOrganization({ enforce_2fa })}
                            disabledReason={adminRestrictionReason}
                        />
                    </div>
                </PayGateMini>
            </div>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Invite settings
                </Heading>
                <PayGateMini
                    feature={AvailableFeature.ORGANIZATION_INVITE_SETTINGS}
                    featureDetail="organization-member-and-project-invites"
                >
                    <div className="flex flex-col gap-2">
                        <Text size="xs" render={<p className="m-0" />}>
                            Control who can send organization invites.
                        </Text>
                        <QuillSettingSwitch
                            label={
                                <span>
                                    Members can invite others to join <i>{currentOrganization?.name}</i>
                                </span>
                            }
                            dataAttr="org-members-can-invite-toggle"
                            checked={!!currentOrganization?.members_can_invite}
                            onCheckedChange={(members_can_invite) => updateOrganization({ members_can_invite })}
                            disabledReason={adminRestrictionReason}
                        />
                        <Text size="xs" render={<p className="m-0" />}>
                            Control who can create new projects. Admins and owners can always create projects.
                        </Text>
                        <QuillSettingSwitch
                            label={
                                <span>
                                    Members can create new projects in <i>{currentOrganization?.name}</i>
                                </span>
                            }
                            dataAttr="org-members-can-create-projects-toggle"
                            checked={!!currentOrganization?.members_can_create_projects}
                            onCheckedChange={(members_can_create_projects) =>
                                updateOrganization({ members_can_create_projects })
                            }
                            disabledReason={adminRestrictionReason}
                        />
                    </div>
                </PayGateMini>
            </div>

            {posthog.isFeatureEnabled(FEATURE_FLAGS.MEMBERS_CAN_USE_PERSONAL_API_KEYS) && (
                <div className="flex flex-col gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Security settings
                    </Heading>
                    <PayGateMini
                        feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}
                        featureDetail="organization-members-personal-api-key-access"
                    >
                        <div className="flex flex-col gap-2">
                            <Text size="xs" render={<p className="m-0" />}>
                                Configure security permissions for organization members.
                            </Text>
                            <QuillSettingSwitch
                                label="Members can use personal API keys"
                                help="Organization admins and owners can always use personal API keys regardless of this setting."
                                dataAttr="org-members-can-use-personal-api-keys-toggle"
                                checked={!!currentOrganization?.members_can_use_personal_api_keys}
                                onCheckedChange={(members_can_use_personal_api_keys) =>
                                    updateOrganization({ members_can_use_personal_api_keys })
                                }
                                disabledReason={adminRestrictionReason}
                            />
                        </div>
                    </PayGateMini>
                </div>
            )}
        </div>
    )
}
