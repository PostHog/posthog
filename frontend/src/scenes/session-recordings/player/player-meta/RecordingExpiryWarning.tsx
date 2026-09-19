import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS } from 'lib/constants'
import { recordingExpiryDialogProps } from 'scenes/session-recordings/player/player-meta/recordingExpiryDialog'
import { getRecordingExportDisabledReasons } from 'scenes/session-recordings/player/recordingExportDisabledReasons'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function RecordingExpiryWarning(): JSX.Element | null {
    const { sessionPlayerMetaData, sessionPlayerData, hasReachedExportFullVideoLimit, logicProps } =
        useValues(sessionRecordingPlayerLogic)
    const { exportRecordingToFile, exportRecordingToVideoFile } = useActions(sessionRecordingPlayerLogic)

    const recordingTtl = sessionPlayerMetaData?.recording_ttl
    const lowTtl = typeof recordingTtl === 'number' && recordingTtl <= SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS

    useEffect(() => {
        if (lowTtl) {
            // Send named properties only. The recording metadata object also holds person properties,
            // distinct IDs, and the start URL, which this expiry metric does not need.
            posthog.capture('recording viewed with very low TTL', {
                session_id: sessionPlayerMetaData?.id,
                recording_ttl: recordingTtl,
                retention_period_days: sessionPlayerMetaData?.retention_period_days,
                expiry_time: sessionPlayerMetaData?.expiry_time,
            })
        }
    }, [sessionPlayerMetaData, lowTtl, recordingTtl])

    if (!lowTtl) {
        return null
    }

    // The export can stop at a paywall or fail after this fires, and no later event reports the
    // outcome, so this counts requests. A count of finished exports has to come from the export pipeline.
    const captureExportRequest = (format: 'mp4' | 'posthog_json'): void => {
        // pinned: analytics event name, renaming it breaks dashboards
        posthog.capture('recording export requested from expiry warning', {
            export_format: format,
            recording_ttl: recordingTtl,
            session_id: sessionPlayerMetaData?.id,
        })
    }

    const dialogProps = recordingExpiryDialogProps({
        recordingTtlDays: recordingTtl,
        expiryTime: sessionPlayerMetaData?.expiry_time,
        exportsAvailable:
            (logicProps.mode ?? SessionRecordingPlayerMode.Standard) === SessionRecordingPlayerMode.Standard,
        exportDisabledReasons: getRecordingExportDisabledReasons(
            sessionPlayerData?.durationMs,
            hasReachedExportFullVideoLimit
        ),
        onExportVideo: () => {
            captureExportRequest('mp4')
            exportRecordingToVideoFile()
        },
        onExportJson: () => {
            captureExportRequest('posthog_json')
            exportRecordingToFile()
        },
    })

    return (
        <div className="font-medium">
            <LemonButton
                status="danger"
                size="xsmall"
                className="rounded-none"
                data-attr="recording-ttl-dialog"
                onClick={() => LemonDialog.open(dialogProps)}
                noPadding
            >
                {dialogProps.title}
            </LemonButton>
        </div>
    )
}
