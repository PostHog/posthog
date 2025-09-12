import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
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

    if (logItem.activity === 'share_login_success') {
        const afterData = logItem.detail.changes?.[0]?.after as any
        const clientIp = afterData?.client_ip || 'unknown IP'
        const passwordNote = afterData?.password_note || 'unknown password'

        return {
            description: (
                <>
                    <strong>Anonymous user</strong> successfully authenticated to shared session recording{' '}
                    <b>{logItem.detail?.name || 'session recording'}</b> from {clientIp} using password{' '}
                    <strong>{passwordNote}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'share_login_failed') {
        const afterData = logItem.detail.changes?.[0]?.after as any
        const clientIp = afterData?.client_ip || 'unknown IP'

        return {
            description: (
                <>
                    <strong>Anonymous user</strong> failed to authenticate to shared session recording{' '}
                    <b>{logItem.detail?.name || 'session recording'}</b> from {clientIp}
                </>
            ),
        }
    }

    // Fall back to default describer for other activities like 'deleted', 'created', etc.
    return defaultDescriber(logItem, asNotification)
}
