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
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { isObject, objectsEqual } from 'lib/utils'

import { ErrorTrackingGroup } from '~/queries/schema'
import { ActivityScope, UserBasicType } from '~/types'

function DisplayMember({ member }: { member: UserBasicType }): JSX.Element {
    return <ProfilePicture user={member} size="xs" showName />
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    const name = logItem?.detail?.name || 'this one'
    // TODO link needs to be calculated based on the logItem
    return <i>{name}</i>
}

function isUnassigned(candidate: unknown): boolean {
    return (
        isObject(candidate) &&
        'first_name' in candidate &&
        !candidate.first_name &&
        'email' in candidate &&
        !candidate.email
    )
}

function isUserBasicType(candidate: unknown): candidate is UserBasicType {
    return isObject(candidate) && 'first_name' in candidate && 'email' in candidate && 'id' in candidate
}

const errorTrackingGroupActionsMapping: Record<
    keyof ErrorTrackingGroup,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    assignee: (change, logItem) => {
        const { before, after } = change || {}
        const unnassigned_before = isUnassigned(before)
        const unnassigned_after = isUnassigned(after)
        if (unnassigned_before && unnassigned_after) {
            return null
        }
        if (objectsEqual(before, after)) {
            return null
        }
        const beforeUser = isUserBasicType(before)
        const afterUser = isUserBasicType(after)
        if (!beforeUser && !afterUser) {
            return null
        }
        if (unnassigned_before && !unnassigned_after) {
            return {
                description: [
                    <>
                        assigned {nameAndLink(logItem)} to <DisplayMember member={after as UserBasicType} />.
                    </>,
                ],
            }
        }
        if (!unnassigned_before && unnassigned_after) {
            return {
                description: [
                    <>
                        unassigned {nameAndLink(logItem)} from <DisplayMember member={before as UserBasicType} />.
                    </>,
                ],
            }
        }
        return {
            description: [
                <>
                    changed assignee from <DisplayMember member={before as UserBasicType} /> to{' '}
                    <DisplayMember member={after as UserBasicType} />
                    on {nameAndLink(logItem)}.
                </>,
            ],
        }
    },
    merged_fingerprints(change: ActivityChange | undefined, logItem?: ActivityLogItem): ChangeMapping | null {
        const lenBefore = Array.isArray(change?.before) ? change?.before.length || 0 : 0
        const lenAfter = Array.isArray(change?.after) ? change?.after.length || 0 : 0
        const mergeCountChange = lenAfter - lenBefore
        return {
            description: [
                <>
                    merged {mergeCountChange} groups into {nameAndLink(logItem)}.
                </>,
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
