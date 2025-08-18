import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Link } from 'lib/lemon-ui/Link'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { urls } from 'scenes/urls'

import { getFilterLabel } from '~/taxonomy/helpers'
import { EntityFilter } from '~/types'

const nameOrId = (name?: string | null, id?: string | null): string => {
    if (name) {
        return name.length > 50 ? name.slice(0, 50) + '...' : name
    }
    return id ? `Tag ${id}` : 'Unnamed tag'
}

const getRelatedObjectDescription = (context: any, preposition?: 'to' | 'from'): JSX.Element | null => {
    if (!context || !context.related_object_type || !context.related_object_id) {
        return null
    }

    const objectType = context.related_object_type
    const objectTypeDisplayName = objectType.replace(/_/g, ' ')
    const objectId = context.related_object_id
    let objectName = context.related_object_name || `${objectType} ${objectId}`

    const getDisplayName = (): string => {
        if (objectType === 'event_definition') {
            return getDisplayNameFromEntityFilter({ name: objectName } as EntityFilter, false) || objectName
        }
        if (objectType === 'property_definition') {
            return getFilterLabel(objectName, TaxonomicFilterGroupType.EventProperties)
        }
        return objectName
    }

    const displayName = getDisplayName()

    const getObjectLink = () => {
        switch (objectType) {
            case 'dashboard':
                return (
                    <Link to={urls.dashboard(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            case 'insight':
                return (
                    <Link to={urls.insightView(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            case 'action':
                return (
                    <Link to={urls.action(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            case 'feature_flag':
                return (
                    <Link to={urls.featureFlag(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            case 'event_definition':
                return (
                    <Link to={urls.eventDefinition(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            case 'property_definition':
                return (
                    <Link to={urls.propertyDefinition(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            case 'experiment_saved_metric':
                return (
                    <Link to={urls.experimentsSharedMetric(objectId)}>
                        <strong>{displayName}</strong>
                    </Link>
                )
            default:
                return <strong>{displayName}</strong>
        }
    }

    return (
        <>
            {preposition && `${preposition} `}
            {objectTypeDisplayName} {getObjectLink()}
        </>
    )
}

export function tagActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope === 'TaggedItem') {
        return taggedItemActivityDescriber(logItem, asNotification)
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the tag{' '}
                    <strong>{nameOrId(logItem?.detail?.name, logItem?.item_id)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the tag{' '}
                    <strong>{nameOrId(logItem?.detail?.name, logItem?.item_id)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated the tag{' '}
                    <strong>{nameOrId(logItem?.detail?.name, logItem?.item_id)}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrId(logItem?.detail?.name, logItem?.item_id))
}

function taggedItemActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const context = logItem?.detail?.context
    const tagName = context?.tag_name || ''
    const relatedObjectDesc = getRelatedObjectDescription(context) // No preposition for "tagged"
    const relatedObjectDescFrom = getRelatedObjectDescription(context, 'from')

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> tagged {relatedObjectDesc} with tag{' '}
                    <strong>{tagName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> removed tag <strong>{tagName}</strong>{' '}
                    {relatedObjectDescFrom}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, tagName)
}
