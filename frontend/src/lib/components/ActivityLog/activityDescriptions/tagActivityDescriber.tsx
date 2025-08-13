import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

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
    const objectName = context.related_object_name || `${objectType} ${context.related_object_id}`

    return (
        <>
            {preposition && `${preposition} `}
            {objectType} <strong>{objectName}</strong>
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
