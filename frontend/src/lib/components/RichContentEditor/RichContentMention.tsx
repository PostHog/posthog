import { useValues } from 'kea'

import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { QuillMemberHoverCard } from 'lib/components/QuillMemberHoverCard/QuillMemberHoverCard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { membersLogic } from '~/models/membersLogic'

export const RichContentMention = ({ id }: { id?: number }): JSX.Element => {
    const { meFirstMembers } = useValues(membersLogic)

    const member = meFirstMembers.find((member) => member.user.id === id)
    const isQuill = useFeatureFlag('TODAY_RAIL_NAV')
    const pill = (
        <span className="ph-no-capture bg-fill-highlight-100 px-1 rounded font-medium">
            @{member?.user.first_name ?? '(Member)'}
        </span>
    )

    if (isQuill) {
        return <QuillMemberHoverCard user={member?.user}>{pill}</QuillMemberHoverCard>
    }

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
            {pill}
        </Tooltip>
    )
}
