import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { fullNameOrEmail } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'
import { OrganizationMemberType } from '~/types'

import { changeMemberLevelWithConfirmation, memberActionOptions, memberLevelChangeLabel } from './memberActions'
import { memberOffboardingLogic } from './memberOffboardingLogic'
import { memberProjectAccessLogic } from './memberProjectAccessLogic'

export function QuillMemberActionsMenu({ member }: { member: OrganizationMemberType }): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { changeMemberAccessLevel } = useActions(membersLogic)
    const { open: openOffboarding } = useActions(memberOffboardingLogic)
    const { openProjectAccessModal } = useActions(memberProjectAccessLogic)

    if (!user) {
        return null
    }

    const { allowDeletion, allowedLevels, disallowedReason } = memberActionOptions(user, currentOrganization, member)
    const label = `Actions for ${fullNameOrEmail(member.user)}`

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button size="icon" aria-label={label} tooltip={label} />}>
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem
                    onClick={() => openProjectAccessModal(member)}
                    data-attr="org-member-manage-project-access"
                >
                    Manage project access
                </DropdownMenuItem>
                {!disallowedReason &&
                    allowedLevels.map((listLevel) => (
                        <DropdownMenuItem
                            key={`${member.user.uuid}-level-${listLevel}`}
                            onClick={() =>
                                changeMemberLevelWithConfirmation(user, member, listLevel, changeMemberAccessLevel)
                            }
                            data-test-level={listLevel}
                        >
                            {memberLevelChangeLabel(member, listLevel)}
                        </DropdownMenuItem>
                    ))}
                {allowDeletion && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            data-attr="delete-org-membership"
                            onClick={() => openOffboarding(member)}
                        >
                            {member.user.uuid !== user.uuid ? 'Remove from organization' : 'Leave organization'}
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
