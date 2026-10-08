import { summarizeDescriptionChange } from 'lib/components/ActivityLog/activityDescriptions/changeDescriptions'
import { describeMappedChanges } from 'lib/components/ActivityLog/activityDescriptions/describeMappedChanges'
import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    Description,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
    detectBoolean,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { IconVerifiedEvent } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

const dataManagementActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    description: (change) => {
        return {
            summary: summarizeDescriptionChange(change),
            preview: typeof change?.after === 'string' ? change.after : undefined,
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
            summary: [
                <>
                    marked as {verified ? 'verified' : 'unverified'} {verified && <IconVerifiedEvent />}
                </>,
            ],
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
        const changes = describeMappedChanges(
            logItem,
            dataManagementActionsMapping,
            <>
                <DescribeType logItem={logItem} />: {nameAndLink(logItem)}
            </>,
            <>
                on <DescribeType logItem={logItem} /> {nameAndLink(logItem)}
            </>
        )
        if (changes) {
            return changes
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            summary: activityLogSummary(
                logItem,
                <>
                    Deleted the <DescribeType logItem={logItem} />
                </>,
                nameAndLink(logItem)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted <DescribeType logItem={logItem} />{' '}
                    {nameAndLink(logItem)}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
