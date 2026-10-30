import clsx from 'clsx'
import { useValues } from 'kea'
import { memo } from 'react'

import { IconBug, IconCursorClick, IconKeyboard, IconLive } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import { TimestampFormat, playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { gatherIconProperties } from './gatherIconProperties'
import { ItemCheckbox } from './ItemCheckbox'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import { DEFAULT_RECORDING_FILTERS_ORDER_BY, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { SortMetric } from './SortMetric'
import { UnwatchedIndicator } from './UnwatchedIndicator'

export interface SessionRecordingPreviewFeedProps {
    recording: SessionRecordingType
    isActive?: boolean
    selectable?: boolean
}

export const SessionRecordingPreviewFeed = memo(
    function SessionRecordingPreviewFeed({
        recording,
        isActive,
        selectable = false,
    }: SessionRecordingPreviewFeedProps): JSX.Element {
        const { playlistTimestampFormat } = useValues(playerSettingsLogic)
        const { filters, nextSessionRecording } = useValues(sessionRecordingsPlaylistLogic)
        const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)

        const order = filters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY
        const recordingProperties = recordingPropertiesById[recording.id]
        const loading = !recordingProperties && recordingPropertiesLoading
        const iconProperties = gatherIconProperties(recordingProperties, recording)
        const errorCount = recording.console_error_count ?? 0
        const startUrl = recording.start_url?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]
        // nextSessionRecording is undefined while autoplay is off, so the label disappears with it
        const upNext = !isActive && nextSessionRecording?.id === recording.id

        return (
            <DraggableToNotebook href={urls.replaySingle(recording.id)}>
                <div
                    className={clsx(
                        'SessionRecordingPreview SessionRecordingPreview--compact group flex items-start gap-x-2 overflow-hidden cursor-pointer py-2 px-2 text-[11px]',
                        isActive && 'SessionRecordingPreview--active'
                    )}
                >
                    {selectable && (
                        <span className="shrink-0 flex items-center self-center [&_label]:min-h-0">
                            <ItemCheckbox recording={recording} />
                        </span>
                    )}
                    {loading ? (
                        <LemonSkeleton className="w-16 h-16 shrink-0 rounded" />
                    ) : (
                        <div className="grid grid-cols-2 grid-rows-2 gap-0.5 p-0.5 w-16 h-16 shrink-0 rounded border bg-surface-secondary overflow-hidden ph-no-capture">
                            {iconProperties.map(({ property, value, label }) => (
                                <Tooltip key={property} title={label}>
                                    <span className="flex items-center justify-center rounded-sm bg-surface-primary leading-none text-base">
                                        <PropertyIcon property={property} value={value} />
                                    </span>
                                </Tooltip>
                            ))}
                        </div>
                    )}
                    <div className="grow min-w-0 flex flex-col gap-y-0.5">
                        <div className="flex items-start gap-x-1.5">
                            <span
                                className={clsx(
                                    'line-clamp-2 grow text-xs leading-snug ph-no-capture',
                                    recording.viewed ? 'font-medium' : 'font-semibold'
                                )}
                            >
                                {asDisplay(recording.person)}
                            </span>
                            {upNext && (
                                <Tooltip title="Autoplay opens this recording when the current one ends.">
                                    <LemonTag size="small" className="shrink-0" data-attr="feed-up-next">
                                        Up next
                                    </LemonTag>
                                </Tooltip>
                            )}
                            {recording.ongoing && (
                                <Tooltip title="This recording is still ongoing - we received data within the last 5 minutes.">
                                    <IconLive className="shrink-0 mt-0.5 animate-[pulse_1s_ease-out_infinite] text-primary-3000" />
                                </Tooltip>
                            )}
                            {!recording.viewed && (
                                <span className="shrink-0 pt-1">
                                    <UnwatchedIndicator otherViewersCount={recording.viewers?.length || 0} />
                                </span>
                            )}
                        </div>
                        {recording.matches_filters === false && (
                            <Tooltip title="This recording is listed only because it's open. It doesn't match the current filters.">
                                <LemonTag type="warning" size="small" className="self-start">
                                    Doesn't match filters
                                </LemonTag>
                            </Tooltip>
                        )}
                        <div className="flex items-center gap-x-2 flex-wrap text-secondary">
                            <Tooltip title="Clicks">
                                <span className="flex items-center gap-x-0.5 shrink-0">
                                    <IconCursorClick />
                                    {recording.click_count}
                                </span>
                            </Tooltip>
                            <Tooltip title="Key presses">
                                <span className="flex items-center gap-x-0.5 shrink-0">
                                    <IconKeyboard />
                                    {recording.keypress_count}
                                </span>
                            </Tooltip>
                            {errorCount > 0 && order !== 'console_error_count' && (
                                <Tooltip title="Console errors">
                                    <span className="flex items-center gap-x-0.5 shrink-0 text-danger">
                                        <IconBug />
                                        {errorCount}
                                    </span>
                                </Tooltip>
                            )}
                            {playlistTimestampFormat === TimestampFormat.Relative ? (
                                <TZLabel className="shrink-0" time={recording.start_time} placement="right" />
                            ) : (
                                <SimpleTimeLabel
                                    startTime={recording.start_time}
                                    timestampFormat={playlistTimestampFormat}
                                />
                            )}
                            <span className="grow" />
                            <span className="shrink-0 font-semibold">
                                <SortMetric recording={recording} order={order} />
                            </span>
                        </div>
                        {startUrl && (
                            <span
                                title={`First URL: ${recording.start_url}`}
                                className="truncate text-secondary ph-no-capture"
                            >
                                {startUrl}
                            </span>
                        )}
                    </div>
                </div>
            </DraggableToNotebook>
        )
    },
    (prevProps, nextProps) =>
        prevProps.recording.id === nextProps.recording.id &&
        // The open recording stays listed when filters change, with matches_filters flipped, so the id alone would
        // keep the row stale.
        prevProps.recording.matches_filters === nextProps.recording.matches_filters &&
        // Mark watched and a session ending reload the same ids with viewed and ongoing flipped.
        prevProps.recording.viewed === nextProps.recording.viewed &&
        prevProps.recording.ongoing === nextProps.recording.ongoing &&
        prevProps.recording.viewers?.length === nextProps.recording.viewers?.length &&
        prevProps.isActive === nextProps.isActive &&
        prevProps.selectable === nextProps.selectable
)
