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

import { ErrorTrackingGroup } from '~/queries/schema'
import { ActivityScope } from '~/types'

const errorTrackingGroupActionsMapping: Record<
    keyof ErrorTrackingGroup,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    assignee: () => null,
    merged_fingerprints(change: ActivityChange | undefined): ChangeMapping | null {
        const lenBefore = Array.isArray(change?.before) ? change?.before.length || 0 : 0
        const lenAfter = Array.isArray(change?.after) ? change?.after.length || 0 : 0
        const mergeCountChange = lenAfter - lenBefore
        return {
            // TODO need to be able to name the group here?
            description: [<>merged {mergeCountChange} groups into this one.</>],
        }
    },
    status: () => null,

    /** readonly / computed fields aren't described */
    volume: () => null,
    first_seen: () => null,
    last_seen: () => null,
    description: () => null,
    exception_type: () => null,
    fingerprint: () => null,
    occurrences: () => null,
    sessions: () => null,
    users: () => null,
}

export function errorTrackingActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.ERROR_TRACKING_GROUP) {
        console.error('team describer received a non-error tracking activity')
        return { description: null }
    }

    if (logItem.activity == 'changed' || logItem.activity == 'updated' || logItem.activity == 'merged') {
        let changes: Description[] = []
        let changeSuffix: Description | undefined = undefined

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !errorTrackingGroupActionsMapping[change.field]) {
                continue //  not all fields are describable
            }

            const actionHandler = errorTrackingGroupActionsMapping[change.field]
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

    return defaultDescriber(logItem, asNotification, 'error tracking group')
}
