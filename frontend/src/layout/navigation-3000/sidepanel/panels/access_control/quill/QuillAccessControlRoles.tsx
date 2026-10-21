import { useAsyncActions, useValues } from 'kea'

import { Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AvailableFeature, RoleMemberType, RoleType } from '~/types'

import { QuillPeopleAvatars } from '../../../components/QuillPeopleAvatars'
import { accessControlLogic } from '../accessControlLogic'
import { QuillAccessLevelSelect } from './QuillAccessLevelSelect'
import { QuillAccessSection } from './QuillAccessSection'
import { QuillRemoveAccessButton } from './QuillRemoveAccessButton'

export function QuillAccessControlRoles(): JSX.Element {
    const { accessControlRoles, addableRoles, rolesById, availableLevels, accessControlsLoading } =
        useValues(accessControlLogic)
    // Each change saves the whole list, so a second change before the first lands could overwrite it.
    const savingReason = accessControlsLoading ? 'Saving…' : undefined
    const { updateAccessControlRoles } = useAsyncActions(accessControlLogic)

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
                    <QuillAccessLevelSelect
                        level={access_level}
                        levels={availableLevels}
                        disabledReason={savingReason}
                        onChange={(level) => void updateAccessControlRoles([{ role, level }])}
                    />
                    <QuillRemoveAccessButton
                        subject="role"
                        disabledReason={savingReason}
                        onConfirm={() => void updateAccessControlRoles([{ role, level: null }])}
                    />
                </ItemActions>
            </Item>
        )
    })

    return (
        <QuillAccessSection
            title="Roles"
            subject="role"
            emptyText="No roles have their own access rule yet."
            feature={AvailableFeature.ROLE_BASED_ACCESS}
            placeholder="Search for roles to add…"
            nothingToAddText="No roles left to add. Create roles in organization settings."
            onAdd={(keys, level) => updateAccessControlRoles(keys.map((role) => ({ role, level })))}
            options={addableRoles.map((role: RoleType) => ({
                key: role.id,
                searchLabel: role.name,
                name: role.name,
            }))}
        >
            {rows}
        </QuillAccessSection>
    )
}
