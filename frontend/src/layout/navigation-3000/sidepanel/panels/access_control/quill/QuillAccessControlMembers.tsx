import { useAsyncActions, useValues } from 'kea'

import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import {
    AccessControlLevel,
    AccessControlTypeMember,
    AccessControlTypeOrganizationAdmins,
    AvailableFeature,
    OrganizationMemberType,
} from '~/types'

import { QuillPeopleAvatars } from '../../../components/QuillPeopleAvatars'
import { accessControlLogic } from '../accessControlLogic'
import { QuillAccessLevelSelect } from './QuillAccessLevelSelect'
import { QuillAccessSection } from './QuillAccessSection'
import { QuillRemoveAccessButton } from './QuillRemoveAccessButton'

export function QuillAccessControlMembers(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { resource, membersById, addableMembers, accessControlMembers, availableLevels, accessControlsLoading } =
        useValues(accessControlLogic)
    // Each change saves the whole list, so a second change before the first lands could overwrite it.
    const savingReason = accessControlsLoading ? 'Saving…' : undefined
    const { updateAccessControlMembers } = useAsyncActions(accessControlLogic)

    if (!user) {
        return null
    }

    // TODO(@zach): show project admins (that are not organization admins) in the list
    const rows = accessControlMembers.map((ac: AccessControlTypeMember | AccessControlTypeOrganizationAdmins) => {
        if (ac.resource === 'organization') {
            const admins = (ac as AccessControlTypeOrganizationAdmins).organization_admin_members ?? []
            return (
                <Item key="organization-admins" size="sm" variant="outline">
                    <ItemMedia>
                        <QuillPeopleAvatars
                            people={admins.map((id) => ({
                                email: membersById[id]?.user.email,
                                name: fullName(membersById[id]?.user),
                            }))}
                        />
                    </ItemMedia>
                    <ItemContent className="min-w-0">
                        <ItemDescription>
                            {admins.length > 1
                                ? 'have access as organization admins'
                                : 'has access as an organization admin'}
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        {/* Shown as disabled for visibility */}
                        <QuillAccessLevelSelect
                            level={resource === 'project' ? AccessControlLevel.Admin : AccessControlLevel.Editor}
                            disabled
                            levels={availableLevels}
                            onChange={() => {}}
                        />
                    </ItemActions>
                </Item>
            )
        }

        const memberAc = ac as AccessControlTypeMember
        const member: OrganizationMemberType | undefined = membersById[memberAc.organization_member]
        const name = fullName(member?.user)
        return (
            <Item key={memberAc.organization_member} size="sm" variant="outline">
                <ItemMedia>
                    <QuillPersonAvatar name={name} email={member?.user.email} />
                </ItemMedia>
                <ItemContent className="ph-no-capture min-w-0">
                    <ItemTitle className="w-full">
                        <span className="truncate">{member?.user.uuid == user.uuid ? `${name} (you)` : name}</span>
                    </ItemTitle>
                    <ItemDescription className="truncate">{member?.user.email}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <QuillAccessLevelSelect
                        level={memberAc.access_level}
                        levels={availableLevels}
                        disabledReason={savingReason}
                        onChange={(level) =>
                            void updateAccessControlMembers([{ member: memberAc.organization_member as string, level }])
                        }
                    />
                    <QuillRemoveAccessButton
                        subject="member"
                        disabledReason={savingReason}
                        onConfirm={() =>
                            void updateAccessControlMembers([
                                { member: memberAc.organization_member as string, level: null },
                            ])
                        }
                    />
                </ItemActions>
            </Item>
        )
    })

    return (
        <QuillAccessSection
            title="Members"
            subject="member"
            emptyText="No members have their own access rule yet."
            feature={AvailableFeature.ACCESS_CONTROL}
            placeholder="Search for team members to add…"
            nothingToAddText="No members left to add."
            onAdd={(keys, level) => updateAccessControlMembers(keys.map((member) => ({ member, level })))}
            options={addableMembers.map((member: OrganizationMemberType) => ({
                key: member.id,
                searchLabel: `${fullName(member.user)} ${member.user.email}`,
                name: fullName(member.user),
                email: member.user.email,
            }))}
        >
            {rows}
        </QuillAccessSection>
    )
}
