import { useValues } from 'kea'

import { ProfilePicture } from '@posthog/lemon-ui'

import { membersLogic } from 'scenes/organization/membersLogic'

export interface AccountRelationshipHoldersProps {
    userIds: number[]
    column: string
}

export function AccountRelationshipHolders({ userIds, column }: AccountRelationshipHoldersProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)
    const users = userIds.map((id) => meFirstMembers.find((member) => member.user.id === id)?.user ?? null)
    return (
        <div data-attr={`accounts-${column}-cell`} className="flex flex-wrap items-center gap-2">
            {users.length === 0 ? (
                <span className="text-muted">Unassigned</span>
            ) : (
                users.map((user, index) => (
                    <span key={userIds[index]} className="inline-flex items-center gap-1 text-sm">
                        {user ? <ProfilePicture user={user} size="sm" /> : null}
                        {user?.email ?? 'Unknown user'}
                    </span>
                ))
            )}
        </div>
    )
}
