import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
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

const getContextDescription = (context: any): JSX.Element | null => {
    if (!context) {
        return null
    }

    if (context.scope === 'dashboard_item' && context.dashboard_item_short_id) {
        return (
            <>
                {' '}
                on insight{' '}
                <Link to={urls.insightView(context.dashboard_item_short_id)}>
                    {context.dashboard_item_name || context.dashboard_item_short_id}
                </Link>
            </>
        )
    }

    if (context.scope === 'dashboard' && context.dashboard_id) {
        return (
            <>
                {' '}
                on dashboard{' '}
                <Link to={urls.dashboard(context.dashboard_id)}>
                    {context.dashboard_name || `Dashboard ${context.dashboard_id}`}
                </Link>
            </>
        )
    }

    if (context.scope === 'recording' && context.recording_id) {
        return (
            <>
                {' '}
                on <Link to={urls.replaySingle(context.recording_id)}>a session replay</Link>
            </>
        )
    }

    if (context.scope === 'project') {
        return <> for the current project</>
    }

    if (context.scope === 'organization') {
        return <> for the current organization</>
    }

    return null
}

export function annotationActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Annotation') {
        console.error('annotation describer received a non-annotation activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        const contextDesc = getContextDescription(logItem?.detail?.context)
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the annotation "
                    {nameOrLinkToAnnotation(logItem?.item_id, logItem?.detail.name)}"{contextDesc}
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

        const contextDesc = getContextDescription(logItem?.detail?.context)
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the annotation: {displayName}
                    {contextDesc}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const contextDesc = getContextDescription(logItem?.detail?.context)
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated the annotation:{' '}
                    {nameOrLinkToAnnotation(logItem?.item_id, logItem?.detail.name)}
                    {contextDesc}
                </>
            ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToAnnotation(logItem?.detail.short_id))
}
