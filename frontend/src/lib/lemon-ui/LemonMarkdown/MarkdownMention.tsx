import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { membersLogic } from 'scenes/organization/membersLogic'

export interface MarkdownMentionProps {
    /** The user UUID to mention */
    userId?: string
    /** The display name if user ID is not available */
    displayName?: string
}

export function MarkdownMention({ userId, displayName }: MarkdownMentionProps): JSX.Element {
    const { meFirstMembers } = useValues(membersLogic)

    const member = userId ? meFirstMembers.find((member) => member.user.uuid === userId) : null

    const name = member?.user.first_name || displayName || '(Member)'

    return member ? (
        <Tooltip
            title={
                member ? (
                    <div className="p-2 flex items-center gap-2">
                        <ProfilePicture user={member.user} size="xl" />
                        <div>
                            <div className="font-bold">
                                {member.user.first_name} {member.user.last_name}
                            </div>
                            <div className="text-sm">{member.user.email}</div>
                        </div>
                    </div>
                ) : (
                    <div className="p-2">
                        <div className="font-bold">{displayName}</div>
                        <div className="text-sm text-muted">User not found</div>
                    </div>
                )
            }
        >
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">
                @{name}
            </span>
        </Tooltip>
    ) : (
        <span>{displayName}</span>
    )
}
