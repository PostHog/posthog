import {
    ActivityLogItem,
    defaultDescriber,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'
import { isObject } from 'lib/utils'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs } from 'lib/dayjs'

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
    } else if (logItem.activity === 'tagged_user') {
        const recordingId =
            isObject(logItem.detail.changes?.[0]?.after) && logItem.detail.changes?.[0]?.after?.annotation_recording_id

        if (!recordingId || typeof recordingId !== 'string') {
            console.error('replay describer received a replay comment with no recording id', logItem)
            return { description: null }
        }

        const commentTime =
            isObject(logItem.detail.changes?.[0]?.after) && logItem.detail.changes?.[0]?.after.annotation_date_marker

        return {
            description: (
                <>
                    <strong>{userNameForLogItem(logItem)}</strong> tagged you in a recording comment{' '}
                    <ViewRecordingButton
                        sessionId={recordingId}
                        timestamp={commentTime as string | Dayjs | undefined}
                        type="secondary"
                        fullWidth={false}
                        inModal={true}
                    />
                </>
            ),
        }
    }

    // Fall back to default describer for other activities like 'deleted', 'created', etc.
    return defaultDescriber(logItem, asNotification)
}
