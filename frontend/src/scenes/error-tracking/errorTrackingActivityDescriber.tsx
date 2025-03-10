import { Link } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    defaultDescriber,
    Description,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { objectsEqual } from 'lib/utils'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { AssigneeDisplay } from './AssigneeDisplay'
import { assigneeSelectLogic } from './assigneeSelectLogic'

type ErrorTrackingIssueAssignee = Exclude<ErrorTrackingIssue['assignee'], null>

function AssigneeRenderer({ assignee }: { assignee: ErrorTrackingIssueAssignee }): JSX.Element {
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [])

    return (
        <AssigneeDisplay assignee={assignee}>
            {({ displayAssignee }) => (
                <span className="flex gap-x-0.5">
                    {displayAssignee.icon}
                    <span>{displayAssignee.displayName}</span>
                </span>
            )}
        </AssigneeDisplay>
    )
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    const name = logItem?.detail.name
    return logItem?.item_id ? (
        <Link to={urls.errorTrackingIssue(logItem.item_id)}>{name || 'an issue'}</Link>
    ) : name ? (
        <>{name}</>
    ) : (
        <i>an issue</i>
    )
}

const errorTrackingIssueActionsMapping: Record<
    keyof ErrorTrackingIssue,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    assignee: (change, logItem) => {
        const { before, after } = change || {}
        const unassignedBefore = before === null
        const unassignedAfter = after === null
        if (unassignedBefore && unassignedAfter) {
            return null
        }
        if (objectsEqual(before, after)) {
            return null
        }
        if (!before && !after) {
            return null
        }

        const wasAssigned = unassignedBefore && !unassignedAfter
        const wasUnassigned = !unassignedBefore && unassignedAfter

        return {
            description: [
                wasAssigned ? (
                    <>
                        assigned {nameAndLink(logItem)} to{' '}
                        <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} />
                    </>
                ) : wasUnassigned ? (
                    <>
                        unassigned {nameAndLink(logItem)} from{' '}
                        <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} />
                    </>
                ) : (
                    <>
                        changed assignee from <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} /> to{' '}
                        <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} /> on {nameAndLink(logItem)}
                    </>
                ),
            ],
        }
    },
    status: (change, logItem) => {
        const { before, after } = change || {}
        if (!before || !after) {
            return null
        }
        return {
            description: [
                <>
                    changed status of {nameAndLink(logItem)} from <strong>{before}</strong> to <strong>{after}</strong>
                </>,
            ],
        }
    },

    /** readonly / computed fields aren't described */
    id: () => null,
    name: () => null,
    description: () => null,
    aggregations: () => null,
    first_seen: () => null,
    last_seen: () => null,
    earliest: () => null,
}

export function errorTrackingActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.ERROR_TRACKING_ISSUE) {
        console.error('describer received a non-error tracking activity')
        return { description: null }
    }

    if (logItem.activity == 'updated' || logItem.activity == 'assigned') {
        let changes: Description[] = []
        let changeSuffix: Description | undefined = undefined

        for (const change of logItem.detail.changes || []) {
            const field = change.field as keyof ErrorTrackingIssue

            if (!change?.field || !errorTrackingIssueActionsMapping[field]) {
                continue //  not all fields are describable
            }

            const actionHandler = errorTrackingIssueActionsMapping[field]
            const processedChange = actionHandler(change, logItem)
            if (processedChange === null) {
                continue // unexpected log from backend is indescribable
            }

            const { description, suffix } = processedChange
            if (description) {
                changes = changes.concat(description)
            }

            if (suffix) {
                changeSuffix = suffix
            }
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, 'error tracking issue')
}
