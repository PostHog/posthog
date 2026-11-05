import clsx from 'clsx'

import { IconBug, IconHourglass } from '@posthog/icons'

import { SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS } from 'lib/constants'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { SessionRecordingType } from '~/types'

function formatDuration(seconds: number): string {
    const [hours, minutes, rest] = colonDelimitedDuration(seconds).split(':')
    return hours === '00' ? `${minutes}:${rest}` : `${hours}:${minutes}:${rest}`
}

export function SortMetric({
    recording,
    order,
}: {
    recording: SessionRecordingType
    order: RecordingsQuery['order']
}): JSX.Element {
    if (order === 'console_error_count') {
        return (
            <span className="flex items-center gap-x-0.5 font-semibold">
                <IconBug className="text-secondary" />
                {recording.console_error_count ?? '-'}
            </span>
        )
    }
    if (order === 'recording_ttl') {
        const ttl = recording.recording_ttl
        const ttlColor =
            ttl !== undefined && ttl <= SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS ? 'text-danger' : undefined
        return (
            <span className={clsx('flex items-center gap-x-0.5', ttlColor)}>
                <IconHourglass />
                {ttl === undefined ? '-' : `${ttl}d`}
            </span>
        )
    }
    const seconds =
        order === 'active_seconds'
            ? recording.active_seconds
            : order === 'inactive_seconds'
              ? recording.inactive_seconds
              : recording.recording_duration
    return <span className="tabular-nums">{seconds === undefined ? '-' : formatDuration(seconds)}</span>
}
