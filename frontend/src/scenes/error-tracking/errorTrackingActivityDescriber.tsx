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

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { ActivityScope } from '~/types'

import { AssigneeDisplay } from './AssigneeDisplay'

type ErrorTrackingIssueAssignee = Exclude<ErrorTrackingIssue['assignee'], null>

function AssigneeRenderer({ assignee }: { assignee: ErrorTrackingIssueAssignee }): JSX.Element {
    return (
        <AssigneeDisplay assignee={assignee}>
            {({ displayAssignee }) => (
                <span className="space-x-0.5">
                    {displayAssignee.icon}
                    <span>{displayAssignee.displayName}</span>
                </span>
            )}
        </AssigneeDisplay>
    )
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    debugger
    return 'false'
    // return <Link to={urls.errorTrackingIssue()}>{logItem?.detail.name || 'an issue'}</Link>

    const name = logItem?.detail?.name || 'this one'
    // TODO link needs to be calculated based on the logItem
    return <i>{name}</i>
}

// function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
//     return logItem?.detail?.short_id ? (
//         <Link to={urls.notebook(logItem.detail.short_id)}>{logItem?.detail.name || 'unknown'}</Link>
//     ) : logItem?.detail.name ? (
//         <>{logItem?.detail.name}</>
//     ) : (
//         <i>Untitled</i>
//     )
// }

const errorTrackingIssueActionsMapping: Record<
    keyof ErrorTrackingIssue,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    assignee: (change, logItem) => {
        const { before, after } = change || {}
        const unnassignedBefore = before === null
        const unnassignedAfter = after === null
        if (unnassignedBefore && unnassignedAfter) {
            return null
        }
        if (objectsEqual(before, after)) {
            return null
        }
        if (!before && !after) {
            return null
        }

        const wasAssigned = unnassignedBefore && !unnassignedAfter
        const wasUnassigned = !unnassignedBefore && unnassignedAfter

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
                        <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} />.
                    </>
                ) : (
                    <>
                        changed assignee from <AssigneeRenderer assignee={before as ErrorTrackingIssueAssignee} /> to{' '}
                        <AssigneeRenderer assignee={after as ErrorTrackingIssueAssignee} />
                        on {nameAndLink(logItem)}.
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
                    changed status of {nameAndLink(logItem)} from <strong>{before}</strong> to <strong>{after}</strong>.
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
        console.error('team describer received a non-error tracking activity')
        return { description: null }
    }

    if (logItem.activity == 'updated' || logItem.activity == 'assigned') {
        let changes: Description[] = []
        let changeSuffix: Description | undefined = undefined

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !errorTrackingIssueActionsMapping[change.field]) {
                continue //  not all fields are describable
            }

            const actionHandler = errorTrackingIssueActionsMapping[change.field]
            const processedChange = actionHandler(change, logItem)
            if (processedChange === null) {
                continue // // unexpected log from backend is indescribable
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
