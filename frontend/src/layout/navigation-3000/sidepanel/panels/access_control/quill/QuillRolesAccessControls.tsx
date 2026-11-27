import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Skeleton,
    Text,
} from '@posthog/quill'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { fullName } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'

import { AvailableFeature } from '~/types'

import { QuillPeopleAvatars } from '../../../components/QuillPeopleAvatars'
import { roleAccessControlLogic } from '../roleAccessControlLogic'
import { QuillRoleDetails } from './QuillRoleDetails'
import { QuillRoleDialog } from './QuillRoleDialog'

export function QuillRolesAccessControls(): JSX.Element {
    const { sortedRoles, rolesLoading, selectedRoleId, canEditRoles } = useValues(roleAccessControlLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { selectRoleId, setEditingRoleId } = useActions(roleAccessControlLogic)

    const defaultRoleRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-col items-start gap-2">
            {rolesLoading && !sortedRoles.length ? (
                <div className="flex w-full flex-col gap-2">
                    <Skeleton className="h-10" />
                    <Skeleton className="h-10" />
                </div>
            ) : sortedRoles.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No roles yet.
                </Text>
            ) : (
                <div className="flex w-full flex-col gap-2">
                    {sortedRoles.map((role) => (
                        <Collapsible
                            key={role.id}
                            open={role.id === selectedRoleId}
                            onOpenChange={(open) => selectRoleId(open ? role.id : null)}
                            className="rounded-md border border-border p-2"
                        >
                            <CollapsibleHeader className="flex-wrap">
                                <CollapsibleTrigger iconOnly>{`Members of ${role.name}`}</CollapsibleTrigger>
                                <Text size="xs" weight="medium" render={<span />} className="m-0 truncate">
                                    {role.name}
                                </Text>
                                {role.id === currentOrganization?.default_role_id && (
                                    <Badge variant="info">Default</Badge>
                                )}
                                <span className="ms-auto flex items-center gap-2">
                                    {role.members.length ? (
                                        <QuillPeopleAvatars
                                            people={role.members.map((member) => ({
                                                email: member.user.email,
                                                name: fullName(member.user),
                                            }))}
                                        />
                                    ) : (
                                        <Text size="xs" variant="muted" render={<span />} className="m-0">
                                            No members
                                        </Text>
                                    )}
                                    <Button
                                        onClick={() => setEditingRoleId(role.id)}
                                        disabledReason={!canEditRoles ? 'You cannot edit this' : undefined}
                                    >
                                        Edit
                                    </Button>
                                </span>
                            </CollapsibleHeader>
                            <CollapsibleContent className="pt-2">
                                <QuillRoleDetails roleId={role.id} />
                            </CollapsibleContent>
                        </Collapsible>
                    ))}
                </div>
            )}

            <Button
                variant="primary"
                onClick={() => guardAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS, () => setEditingRoleId('new'))}
                disabledReason={defaultRoleRestrictionReason}
            >
                <IconPlus />
                Add a role
            </Button>

            <QuillRoleDialog />
        </div>
    )
}
