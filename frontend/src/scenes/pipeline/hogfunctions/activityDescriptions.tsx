import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { PipelineNodeTab, PipelineStage } from '~/types'

const nameOrLinkToHogFunction = (id?: string | null, name?: string | null): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? (
        <Link to={urls.pipelineNode(PipelineStage.Destination, `hog-${id}`, PipelineNodeTab.Configuration)}>
            {displayName}
        </Link>
    ) : (
        displayName
    )
}

export function hogFunctionActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'HogFunction') {
        console.error('HogFunction describer received a non-HogFunction activity')
        return { description: null }
    }

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> created the hog function:{' '}
                    {nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> deleted the hog function: {logItem.detail.name}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> updated the hog function:{' '}
                    {nameOrLinkToHogFunction(logItem?.item_id, logItem?.detail.name)}
                </>
            ),
        }
    }
    return defaultDescriber(logItem, asNotification, nameOrLinkToHogFunction(logItem?.detail.short_id))
}
