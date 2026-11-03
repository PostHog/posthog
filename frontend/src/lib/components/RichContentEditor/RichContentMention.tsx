import { useValues } from 'kea'

import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { membersLogic } from '~/models/membersLogic'

export const RichContentMention = ({ id }: { id?: number }): JSX.Element => {
    const { meFirstMembers } = useValues(membersLogic)

    const member = meFirstMembers.find((member) => member.user.id === id)

    return (
        <Tooltip
            title={
                <div className="p-2 flex items-center gap-2">
                    <ProfilePicture user={member?.user} size="xl" />
                    <div className="ph-no-capture">
                        <div className="font-bold">{member?.user.first_name}</div>
                        <div className="text-sm">{member?.user.email}</div>
                    </div>
                </div>
            }
        >
            <span className="ph-no-capture bg-fill-highlight-100 px-1 rounded font-medium">
                @{member?.user.first_name ?? '(Member)'}
            </span>
        </Tooltip>
    )
}
