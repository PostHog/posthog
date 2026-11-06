import {
    ActivityLogItem,
    ActivityLogUserName,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

function describeReplayAuthentication(logItem: ActivityLogItem): HumanizedChange {
    const afterData = logItem.detail.changes?.[0]?.after as any
    const clientIp = afterData?.client_ip || 'unknown IP'
    const passwordNote = afterData?.password_note || 'unknown password'

    return {
        summary: activityLogSummary(
            logItem,
            'Authenticated to the shared recording',
            logItem.detail?.name || 'Session recording',
            `From ${clientIp}, using password ${passwordNote}`,
            <strong>Anonymous user</strong>
        ),
        description: (
            <>
                <strong>Anonymous user</strong> successfully authenticated to shared session recording{' '}
                <b>{logItem.detail?.name || 'session recording'}</b> from {clientIp} using password{' '}
                <strong>{passwordNote}</strong>
            </>
        ),
    }
}

export function replayActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.REPLAY) {
        console.error('replay describer received a non-replay activity')
        return { description: null }
    }

    if (logItem.activity === 'bulk_deleted') {
        return {
            summary: activityLogSummary(
                logItem,
                'Bulk deleted session recordings',
                logItem.detail?.name || 'Session recordings'
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> bulk deleted{' '}
                    <b>{logItem.detail?.name || 'session recordings'}</b>
                </>
            ),
        }
    }

    if (logItem.activity === 'share_login_success') {
        return describeReplayAuthentication(logItem)
    }

    if (logItem.activity === 'share_login_failed') {
        const afterData = logItem.detail.changes?.[0]?.after as any
        const clientIp = afterData?.client_ip || 'unknown IP'

        return {
            summary: activityLogSummary(
                logItem,
                'Failed to authenticate to the shared recording',
                logItem.detail?.name || 'Session recording',
                `From ${clientIp}`,
                <strong>Anonymous user</strong>
            ),
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
