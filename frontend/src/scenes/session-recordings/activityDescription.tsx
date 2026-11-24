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

function describeRecordingExport(logItem: ActivityLogItem): HumanizedChange {
    const payload = logItem.detail.trigger?.payload ?? {}
    const destination = `s3://${payload.bucket ?? 'unknown bucket'}/${payload.prefix ?? ''}`
    const approvedBy = payload.approved_by ?? 'unknown'

    return {
        summary: activityLogSummary(
            logItem,
            'Exported session recordings',
            destination,
            `Approved by ${approvedBy}`,
            <strong>PostHog</strong>
        ),
        description: (
            <>
                <strong>PostHog</strong> exported session recordings to <b>{destination}</b> as role{' '}
                <code>{payload.role_arn ?? 'unknown role'}</code>, approved by <b>{approvedBy}</b>
            </>
        ),
    }
}

function describeBulkDelete(logItem: ActivityLogItem): HumanizedChange {
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

function describeFailedReplayAuthentication(logItem: ActivityLogItem): HumanizedChange {
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

const REPLAY_DESCRIBERS: Record<string, (logItem: ActivityLogItem) => HumanizedChange> = {
    bulk_deleted: describeBulkDelete,
    exported: describeRecordingExport,
    share_login_success: describeReplayAuthentication,
    share_login_failed: describeFailedReplayAuthentication,
}

export function replayActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== ActivityScope.REPLAY) {
        console.error('replay describer received a non-replay activity')
        return { description: null }
    }

    const describe = REPLAY_DESCRIBERS[logItem.activity]
    if (describe) {
        return describe(logItem)
    }

    // Fall back to default describer for other activities like 'deleted', 'created', etc.
    return defaultDescriber(logItem, asNotification)
}
