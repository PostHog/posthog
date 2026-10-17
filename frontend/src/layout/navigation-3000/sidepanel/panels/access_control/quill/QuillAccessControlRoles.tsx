import { useAsyncActions, useValues } from 'kea'
import { useState } from 'react'

import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { Link } from 'lib/lemon-ui/Link'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AvailableFeature, RoleMemberType, RoleType } from '~/types'

import { QuillPeopleAvatars } from '../../../components/QuillPeopleAvatars'
import { accessControlLogic } from '../accessControlLogic'
import { QuillAccessSection } from './QuillAccessSection'
import { QuillAddAccessDialog } from './QuillAddAccessDialog'
import { QuillObjectAccessLevelSelect } from './QuillObjectAccessLevelSelect'
import { QuillRemoveAccessButton } from './QuillRemoveAccessButton'

export function QuillAccessControlRoles(): JSX.Element {
    const {
        accessControlRoles,
        accessControlsLoading,
        addableRoles,
        rolesById,
        availableLevels,
        canEditAccessControls,
    } = useValues(accessControlLogic)
    const { updateAccessControlRoles } = useAsyncActions(accessControlLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const [dialogOpen, setDialogOpen] = useState(false)

    const rows = accessControlRoles.map(({ role, access_level }) => {
        const members: RoleMemberType[] = rolesById[role]?.members ?? []
        return (
            <Item key={role} size="sm" variant="outline">
                <ItemContent className="min-w-0">
                    <ItemTitle className="w-full">
                        <Link
                            to={urls.settings('organization-roles') + `#role=${role}`}
                            className="truncate text-foreground"
                        >
                            {rolesById[role]?.name}
                        </Link>
                    </ItemTitle>
                    {members.length ? (
                        <QuillPeopleAvatars
                            people={members.map((member) => ({
                                email: member.user.email,
                                name: fullName(member.user),
                            }))}
                        />
                    ) : (
                        <ItemDescription>No members</ItemDescription>
                    )}
                </ItemContent>
                <ItemActions>
                    <QuillObjectAccessLevelSelect
                        level={access_level}
                        levels={availableLevels}
                        onChange={(level) => void updateAccessControlRoles([{ role, level }])}
                    />
                    <QuillRemoveAccessButton
                        subject="role"
                        onConfirm={() => void updateAccessControlRoles([{ role, level: null }])}
                    />
                </ItemActions>
            </Item>
        )
    })

    return (
        <>
            <QuillAccessSection
                title="Roles"
                subject="role"
                onAddClick={() => setDialogOpen(true)}
                addDisabledReason={!canEditAccessControls ? 'You cannot edit this' : undefined}
                loading={accessControlsLoading}
                emptyText="No roles have their own access rule yet."
            >
                {rows}
            </QuillAccessSection>
            <QuillAddAccessDialog
                open={dialogOpen}
                onOpenChange={setDialogOpen}
                pickerLabel="Roles"
                placeholder="Search for roles to add…"
                emptyText="No roles left to add. Create roles in organization settings."
                onAdd={async (newValues, level) => {
                    if (guardAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS)) {
                        await updateAccessControlRoles(newValues.map((role) => ({ role, level })))
                        setDialogOpen(false)
                    }
                }}
                options={addableRoles.map((role: RoleType) => ({
                    key: role.id,
                    searchLabel: role.name,
                    name: role.name,
                }))}
            />
        </>
    )
}
