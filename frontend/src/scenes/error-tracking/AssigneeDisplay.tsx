import { Lettermark, ProfilePicture } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { fullName } from 'lib/utils'
import React, { useMemo } from 'react'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { OrganizationMemberType, UserGroup } from '~/types'

import { assigneeSelectLogic } from './assigneeSelectLogic'

export type AssigneeDisplayType = { id: string | number; icon: JSX.Element; displayName?: string }

type AssigneeDisplayRenderProps = {
    children: (props: { displayAssignee: AssigneeDisplayType }) => React.ReactElement
    assignee: ErrorTrackingIssue['assignee']
}

export const groupDisplay = (group: UserGroup, index: number): AssigneeDisplayType => ({
    id: group.id,
    displayName: group.name,
    icon: <Lettermark name={group.name} index={index} rounded />,
})

export const userDisplay = (member: OrganizationMemberType): AssigneeDisplayType => ({
    id: member.user.id,
    displayName: fullName(member.user),
    icon: <ProfilePicture size="md" user={member.user} />,
})

// export const AssigneeDisplay = ({
//     children,
//     assignee,
// }: {
//     children: (props: { displayAssignee: AssigneeDisplayType }) => React.ReactElement
//     assignee: ErrorTrackingIssue['assignee']
// }): React.ReactElement => {
//     const logic = assigneeSelectLogic({ assignee })
//     const { computeAssignee } = useValues(logic)

//     const displayAssignee = useMemo(() => computeAssignee(assignee), [assignee, computeAssignee])

//     return children({
//         displayAssignee,
//     })
// }

export const AssigneeDisplay = ({
    children,
    assignee,
    onClick,
    onMouseEnter,
    onMouseLeave,
}: AssigneeDisplayRenderProps): React.ReactElement => {
    const logic = assigneeSelectLogic({ assignee })
    const { computeAssignee } = useValues(logic)

    const displayAssignee = useMemo(() => computeAssignee(assignee), [assignee, computeAssignee])

    return React.cloneElement(
        children({
            displayAssignee,
        }),
        {
            onClick,
            onMouseEnter,
            onMouseLeave,
        }
    )
}

AssigneeDisplay.displayName = 'AssigneeDisplay'
