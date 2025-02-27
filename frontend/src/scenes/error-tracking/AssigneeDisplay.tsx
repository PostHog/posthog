import { useValues } from 'kea'
import React, { useMemo } from 'react'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { AssigneeDisplayType, assigneeSelectLogic } from './assigneeSelectLogic'

export const AssigneeDisplay = ({
    children,
    assignee,
}: {
    children: (props: { displayAssignee: AssigneeDisplayType }) => React.ReactElement
    assignee: ErrorTrackingIssue['assignee']
}): React.ReactElement => {
    const { computeAssignee } = useValues(assigneeSelectLogic)

    const displayAssignee = useMemo(() => computeAssignee(assignee), [assignee, computeAssignee])

    return children({ displayAssignee })
}
