import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

export function replayActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.REPLAY) {
        console.error('replay describer received a non-replay activity')
        return { description: null }
    }

    if (logItem.activity === 'bulk_deleted') {
        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> bulk deleted{' '}
                    <b>{logItem.detail?.name || 'session recordings'}</b>
                </>
            ),
        }
    }

    // Fall back to default describer for other activities like 'deleted', 'created', etc.
    return defaultDescriber(logItem, asNotification)
}
