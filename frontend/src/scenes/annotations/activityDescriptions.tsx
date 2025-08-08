import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToAnnotation = (id?: string | null, name?: string | null): string | JSX.Element => {
    let displayName = name || '(empty string)'

    // Strip markdown image tags: ![alt](url) format
    displayName = displayName.replace(/!\[([^\]]*)\]\([^)]+\)/g, '').trim() || 'Annotation'

    if (displayName.length > 32) {
        displayName = displayName.slice(0, 32) + '...'
    }

    return id ? <Link to={urls.annotation(parseInt(id))}>{displayName}</Link> : displayName
}

export function annotationActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Annotation') {
        console.error('annotation describer received a non-annotation activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the annotation:{' '}
                    {nameOrLinkToAnnotation(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        let displayName = logItem.detail.name || '(empty string)'
        // Strip markdown image tags for deleted annotations too
        displayName = displayName.replace(/!\[([^\]]*)\]\([^)]+\)/g, '').trim()
        if (!displayName) {
            displayName = '(empty string)'
        }

        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the annotation: {displayName}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated the annotation:{' '}
                    {nameOrLinkToAnnotation(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToAnnotation(logItem?.detail.short_id))
}
