import { IconDownload } from '@posthog/icons'
import { LemonDialogProps, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'
import { RecordingExportDisabledReasons } from 'scenes/session-recordings/player/recordingExportDisabledReasons'
import { urls } from 'scenes/urls'

interface RecordingExpiryDeadline {
    /** How long is left, for a sentence that starts "This recording expires …". */
    inWords: string
    /** The day the recording goes away, or null when "today" already says it. */
    onDate: string | null
}

export function getRecordingExpiryDeadline(recordingTtlDays: number, expiryTime?: string): RecordingExpiryDeadline {
    const expiry = expiryTime ? dayjs(expiryTime) : null
    // Count the days off expiry_time in the viewer's own clock, because the API counts UTC calendar days.
    // For a viewer west of UTC that count is one day more than the date below, so the sentence would
    // contradict itself. Fall back to the API count only when the recording has no expiry_time.
    const daysLeft = expiry?.isValid() ? expiry.startOf('day').diff(dayjs().startOf('day'), 'day') : recordingTtlDays

    if (daysLeft <= 0) {
        return { inWords: 'today', onDate: null }
    }

    return {
        inWords: `in ${daysLeft} ${pluralize(daysLeft, 'day', undefined, false)}`,
        onDate: expiry?.isValid() ? expiry.format('MMMM D, YYYY') : null,
    }
}

export interface RecordingExpiryDialogProps {
    recordingTtlDays: number
    expiryTime?: string
    /** Exports are only offered in the standard player, not in shared or embedded players. */
    exportsAvailable: boolean
    exportDisabledReasons: RecordingExportDisabledReasons
    onExportVideo: () => void
    onExportJson: () => void
}

export function recordingExpiryDialogProps({
    recordingTtlDays,
    expiryTime,
    exportsAvailable,
    exportDisabledReasons,
    onExportVideo,
    onExportJson,
}: RecordingExpiryDialogProps): LemonDialogProps {
    const { inWords, onDate } = getRecordingExpiryDeadline(recordingTtlDays, expiryTime)

    return {
        title: `This recording expires ${inWords}`,
        content: (
            <div className="flex flex-col gap-2">
                <p className="mb-0">
                    PostHog deletes this recording {inWords}
                    {onDate ? `, on ${onDate}` : ''}. The deletion is permanent, and nobody can restore the recording
                    afterwards.
                </p>
                {exportsAvailable && (
                    <p className="mb-0">
                        Export the recording now to keep it. The MP4 file is a video you can watch anywhere. The JSON
                        file loads back into PostHog for playback.
                    </p>
                )}
                <p className="mb-0">
                    A longer <Link to={urls.settings('project-replay', 'replay-retention')}>retention period</Link>{' '}
                    applies to future recordings only. It does not extend this one. Read more about{' '}
                    <Link
                        to="https://posthog.com/docs/session-replay/data-retention"
                        disableClientSideRouting
                        disableDocsPanel
                        target="_blank"
                    >
                        data retention
                    </Link>
                    .
                </p>
            </div>
        ),
        ...(exportsAvailable
            ? {
                  primaryButton: {
                      children: 'Export video (MP4)',
                      icon: <IconDownload />,
                      disabledReason: exportDisabledReasons.video,
                      'data-attr': 'recording-ttl-export-mp4',
                      onClick: onExportVideo,
                  },
                  secondaryButton: {
                      children: 'Export data (JSON)',
                      icon: <IconDownload />,
                      disabledReason: exportDisabledReasons.json,
                      'data-attr': 'recording-ttl-export-posthog-json',
                      onClick: onExportJson,
                  },
                  tertiaryButton: { children: 'Close' },
              }
            : { primaryButton: { children: 'Close' } }),
    }
}
