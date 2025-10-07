import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

const actionActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    name: (change) => {
        return {
            description: [
                <>
                    changed the name from <strong>"{change?.before as string}"</strong> to{' '}
                    <strong>"{change?.after as string}"</strong>
                </>,
            ],
        }
    },
    description: (change) => {
        const before = change?.before as string | null
        const after = change?.after as string | null
        if (!before && after) {
            return {
                description: [
                    <>
                        added description <strong>"{after}"</strong>
                    </>,
                ],
            }
        } else if (before && !after) {
            return {
                description: [
                    <>
                        removed description (was <strong>"{before}"</strong>)
                    </>,
                ],
            }
        }
        return {
            description: [
                <>
                    changed description from <strong>"{before}"</strong> to <strong>"{after}"</strong>
                </>,
            ],
        }
    },
    tags: function onTags(change) {
        const tagsBefore = change?.before as string[] | null
        const tagsAfter = change?.after as string[] | null
        const addedTags = tagsAfter?.filter((t) => tagsBefore?.indexOf(t) === -1) || []
        const removedTags = tagsBefore?.filter((t) => tagsAfter?.indexOf(t) === -1) || []

        const changes: Description[] = []
        if (addedTags.length) {
            changes.push(
                <>
                    added {pluralize(addedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={addedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }
        if (removedTags.length) {
            changes.push(
                <>
                    removed {pluralize(removedTags.length, 'tag', 'tags', false)}{' '}
                    <ObjectTags tags={removedTags} saving={false} style={{ display: 'inline' }} staticOnly />
                </>
            )
        }

        return { description: changes }
    },
    deleted: (change) => {
        const isDeleted = detectBoolean(change?.after)
        return {
            description: [<>{isDeleted ? 'deleted' : 'restored'}</>],
        }
    },
    post_to_slack: (change) => {
        const enabled = detectBoolean(change?.after)
        return {
            description: [<>{enabled ? 'enabled' : 'disabled'} Slack notifications</>],
        }
    },
    slack_message_format: (change) => {
        const before = change?.before as string | null
        const after = change?.after as string | null
        if (!before && after) {
            return {
                description: [<>set Slack message format</>],
            }
        } else if (before && !after) {
            return {
                description: [<>removed Slack message format</>],
            }
        }
        return {
            description: [<>changed Slack message format</>],
        }
    },
    steps: (change) => {
        const beforeSteps = change?.before as any[] | null
        const afterSteps = change?.after as any[] | null
        const beforeCount = beforeSteps?.length || 0
        const afterCount = afterSteps?.length || 0

        if (beforeCount === 0 && afterCount > 0) {
            return {
                description: [<>added {pluralize(afterCount, 'step', 'steps')}</>],
            }
        } else if (beforeCount > 0 && afterCount === 0) {
            return {
                description: [<>removed all {pluralize(beforeCount, 'step', 'steps')}</>],
            }
        } else if (beforeCount !== afterCount) {
            return {
                description: [
                    <>
                        changed step count from <strong>{beforeCount}</strong> to <strong>{afterCount}</strong>
                    </>,
                ],
            }
        }
        return {
            description: [<>updated match steps</>],
        }
    },
    pinned_at: (change) => {
        const isPinned = change?.after !== null
        return {
            description: [<>{isPinned ? 'pinned' : 'unpinned'}</>],
        }
    },
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    const displayName = logItem?.detail?.name || '(empty string)'
    return logItem?.item_id ? (
        <Link to={urls.action(logItem.item_id)}>{displayName}</Link>
    ) : (
        <strong>{displayName}</strong>
    )
}

export function actionActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.ACTION) {
        console.error('action describer received a non-action activity')
        return { description: null }
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created action {nameAndLink(logItem)}
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted action {nameAndLink(logItem)}
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        let changes: Description[] = []
        let changeSuffix: Description = <>on action {nameAndLink(logItem)}</>

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !actionActionsMapping[change.field]) {
                continue
            }

            const actionHandler = actionActionsMapping[change.field]
            const processedChange = actionHandler(change, logItem)
            if (processedChange === null) {
                continue
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

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
