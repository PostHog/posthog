import { describeMappedChanges } from 'lib/components/ActivityLog/activityDescriptions/describeMappedChanges'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    HumanizedChange,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ActivityScope } from '~/types'

const notebookActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    version: () => null, // version will always change, but we don't show it to users
    content: () => {
        return {
            description: [<>changed content</>],
        }
    },
}

function nameAndLink(logItem?: ActivityLogItem): JSX.Element {
    return logItem?.detail?.short_id ? (
        <Link to={urls.notebook(logItem.detail.short_id)}>{logItem?.detail.name || 'unknown'}</Link>
    ) : logItem?.detail.name ? (
        <>{logItem?.detail.name}</>
    ) : (
        <i>Untitled</i>
    )
}

export function notebookActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.NOTEBOOK) {
        console.error('notebook describer received a non-Notebook activity')
        return { description: null }
    }

    if (logItem.activity == 'changed' || logItem.activity == 'updated') {
        const changes = describeMappedChanges(
            logItem,
            notebookActionsMapping,
            nameAndLink(logItem),
            <>on {nameAndLink(logItem)}</>
        )
        if (changes) {
            return changes
        }
    }

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
