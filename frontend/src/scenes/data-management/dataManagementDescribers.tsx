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
import { IconVerifiedEvent } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

const dataManagementActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    description: (change) => {
        return {
            description: [
                <>
                    changed description to <strong>"{change?.after as string}"</strong>
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
    verified: (change, logItem) => {
        const verified = detectBoolean(change?.after)
        return {
            description: [
                <>
                    marked {nameAndLink(logItem)} as <strong>{verified ? 'verified' : 'unverified'}</strong>{' '}
                    {verified && <IconVerifiedEvent />}
                </>,
            ],
            suffix: <></>,
        }
    },
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    return logItem?.item_id ? (
        <Link to={urls.eventDefinition(logItem.item_id)}>{logItem?.detail.name || 'unknown'}</Link>
    ) : logItem?.detail.name ? (
        <>{logItem?.detail.name}</>
    ) : (
        <>unknown</>
    )
}

function DescribeType({ logItem }: { logItem: ActivityLogItem }): JSX.Element {
    const typeDescription = logItem.scope === ActivityScope.EVENT_DEFINITION ? 'event' : 'property'
    if (typeDescription === 'property') {
        return (
            <>
                <span className="highlighted-activity">{logItem.detail?.type}</span> property definition
            </>
        )
    }
    return <>{typeDescription} definition</>
}

export function dataManagementActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.EVENT_DEFINITION && logItem.scope !== ActivityScope.PROPERTY_DEFINITION) {
        console.error('data management describer received a non-data-management activity')
        return { description: null }
    }

    if (logItem.activity == 'changed') {
        let changes: Description[] = []
        let changeSuffix: Description = (
            <>
                on <DescribeType logItem={logItem} /> {nameAndLink(logItem)}
            </>
        )

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !dataManagementActionsMapping[change.field]) {
                continue //  updates have to have a "field" to be described
            }

            const actionHandler = dataManagementActionsMapping[change.field]
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
                        prefix={<strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>}
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted{' '}
                    <DescribeType logItem={logItem} /> {nameAndLink(logItem)}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
