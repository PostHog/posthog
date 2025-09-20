import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
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
        let changes: Description[] = []
        let changeSuffix: Description = <>on {nameAndLink(logItem)}</>

        for (const change of logItem.detail.changes || []) {
            if (!change?.field || !notebookActionsMapping[change.field]) {
                continue //  not all notebook fields are describable
            }

            const actionHandler = notebookActionsMapping[change.field]
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
                        prefix={<strong>{userNameForLogItem(logItem)}</strong>}
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameAndLink(logItem))
}
