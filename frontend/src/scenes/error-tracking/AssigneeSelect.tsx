import { IconPerson } from '@posthog/icons'
import { LemonButton, LemonButtonProps, ProfilePicture } from '@posthog/lemon-ui'
import { MemberSelect } from 'lib/components/MemberSelect'
import { fullName } from 'lib/utils'

import { ErrorTrackingGroup } from '../../queries/schema'

export const AssigneeSelect = ({
    assignee,
    onChange,
    showName = false,
    ...buttonProps
}: {
    assignee: ErrorTrackingGroup['assignee']
    onChange: (userId: number | null) => void
    showName?: boolean
} & Partial<Pick<LemonButtonProps, 'type'>>): JSX.Element => {
    return (
        <MemberSelect
            defaultLabel="Unassigned"
            value={assignee}
            onChange={(user) => {
                const assigneeId = user?.id || null
                onChange(assigneeId)
            }}
        >
            {(user) => (
                <LemonButton
                    tooltip={user?.first_name}
                    icon={
                        user ? (
                            <ProfilePicture size="md" user={user} />
                        ) : (
                            <IconPerson className="rounded-full border border-dashed border-muted text-muted p-0.5" />
                        )
                    }
                    sideIcon={null}
                    {...buttonProps}
                >
                    {showName ? <span className="pl-1">{user ? fullName(user) : 'Unassigned'}</span> : null}
                </LemonButton>
            )}
        </MemberSelect>
    )
}
