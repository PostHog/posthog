import clsx from 'clsx'
import { useValues } from 'kea'
import { memo } from 'react'

import { IconBug, IconCursorClick, IconKeyboard, IconLive } from '@posthog/icons'
import { Badge, Skeleton, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import { TimestampFormat, playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

import { asDisplay } from 'products/persons/frontend/person-utils'

import { gatherIconProperties } from './gatherIconProperties'
import { QuillItemCheckbox } from './QuillItemCheckbox'
import { QuillUnwatchedIndicator } from './QuillUnwatchedIndicator'
import { RecordingRowStat } from './RecordingRowStat'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import { DEFAULT_RECORDING_FILTERS_ORDER_BY, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { SortMetric } from './SortMetric'

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
        const iconProperties = gatherIconProperties(recordingProperties, recording)
        const loading = iconProperties.length === 0 && !recordingProperties && recordingPropertiesLoading
        const errorCount = recording.console_error_count ?? 0
        const startUrl = recording.start_url?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]
        // nextSessionRecording is undefined while autoplay is off, so the label disappears with it
        const upNext = !isActive && nextSessionRecording?.id === recording.id

        return (
            <DraggableToNotebook href={urls.replaySingle(recording.id)}>
                <div
                    data-quill
                    className={clsx(
                        'SessionRecordingPreview SessionRecordingPreview--compact group flex items-center gap-x-2 overflow-hidden cursor-pointer py-2 px-2 text-[11px] text-foreground',
                        isActive && 'SessionRecordingPreview--active'
                    )}
                >
                    {selectable && (
                        <span className="shrink-0 flex items-center self-center">
                            <QuillItemCheckbox recording={recording} />
                        </span>
                    )}
                    {loading ? (
                        <Skeleton className="w-14 h-14 shrink-0 rounded" />
                    ) : (
                        <div className="grid grid-cols-2 grid-rows-2 gap-0.5 p-0.5 w-14 h-14 shrink-0 rounded border border-border bg-muted overflow-hidden ph-no-capture">
                            {iconProperties.map(({ property, value, label }) => (
                                <Tooltip key={property}>
                                    <TooltipTrigger
                                        render={
                                            <span className="flex items-center justify-center rounded-sm bg-card leading-none text-sm" />
                                        }
                                    >
                                        <PropertyIcon property={property} value={value} />
                                    </TooltipTrigger>
                                    <TooltipContent>{label}</TooltipContent>
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
                                <Tooltip>
                                    <TooltipTrigger render={<Badge className="shrink-0" data-attr="feed-up-next" />}>
                                        Up next
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        Autoplay opens this recording when the current one ends.
                                    </TooltipContent>
                                </Tooltip>
                            )}
                            {(recording.ongoing || !recording.viewed) && (
                                <span className="flex items-center gap-x-1.5 shrink-0 h-[1lh] text-xs leading-snug">
                                    {recording.ongoing && (
                                        <Tooltip>
                                            <TooltipTrigger render={<span className="inline-flex" />}>
                                                <IconLive className="animate-[pulse_1s_ease-out_infinite] text-primary-3000" />
                                            </TooltipTrigger>
                                            <TooltipContent>
                                                This recording is still ongoing - we received data within the last 5
                                                minutes.
                                            </TooltipContent>
                                        </Tooltip>
                                    )}
                                    {!recording.viewed && (
                                        <QuillUnwatchedIndicator otherViewersCount={recording.viewers?.length || 0} />
                                    )}
                                </span>
                            )}
                        </div>
                        {recording.matches_filters === false && (
                            <Tooltip>
                                <TooltipTrigger render={<Badge variant="warning" className="self-start" />}>
                                    Doesn't match filters
                                </TooltipTrigger>
                                <TooltipContent>
                                    This recording is listed only because it's open. It doesn't match the current
                                    filters.
                                </TooltipContent>
                            </Tooltip>
                        )}
                        <div className="flex items-center gap-x-2 flex-wrap text-muted-foreground">
                            <RecordingRowStat icon={<IconCursorClick />} value={recording.click_count} label="Clicks" />
                            <RecordingRowStat
                                icon={<IconKeyboard />}
                                value={recording.keypress_count}
                                label="Key presses"
                            />
                            {errorCount > 0 && order !== 'console_error_count' && (
                                <RecordingRowStat
                                    icon={<IconBug />}
                                    value={errorCount}
                                    label="Console errors"
                                    destructive
                                />
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
                                className="truncate text-muted-foreground ph-no-capture"
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
