import { describeMappedChanges } from 'lib/components/ActivityLog/activityDescriptions/describeMappedChanges'
import { shortIdActivityLink } from 'lib/components/ActivityLog/activityDescriptions/shortIdActivityLink'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    HumanizedChange,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
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

export function notebookActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.NOTEBOOK) {
        console.error('notebook describer received a non-Notebook activity')
        return { description: null }
    }

    if (logItem.activity == 'changed' || logItem.activity == 'updated') {
        const changes = describeMappedChanges(
            logItem,
            notebookActionsMapping,
            shortIdActivityLink(logItem, urls.notebook),
            <>on {shortIdActivityLink(logItem, urls.notebook)}</>
        )
        if (changes) {
            return changes
        }
    }

    return defaultDescriber(logItem, asNotification, shortIdActivityLink(logItem, urls.notebook))
}
