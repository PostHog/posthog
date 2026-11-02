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

export interface SessionRecordingPreviewCompactProps {
    recording: SessionRecordingType
    isActive?: boolean
    selectable?: boolean
}

export const SessionRecordingPreviewCompact = memo(
    function SessionRecordingPreviewCompact({
        recording,
        isActive,
        selectable = false,
    }: SessionRecordingPreviewCompactProps): JSX.Element {
        const { playlistTimestampFormat } = useValues(playerSettingsLogic)
        const { filters } = useValues(sessionRecordingsPlaylistLogic)
        const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)

        const order = filters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY
        const recordingProperties = recordingPropertiesById[recording.id]
        const loading = !recordingProperties && recordingPropertiesLoading
        const iconProperties = gatherIconProperties(recordingProperties, recording)
        const errorCount = recording.console_error_count ?? 0

        const tileDetails: { label: string; value: string | undefined }[] = [
            {
                label: 'Location',
                value: [
                    recordingProperties?.['$geoip_city_name'],
                    iconProperties.find((p) => p.property === '$geoip_country_code')?.label,
                ]
                    .filter(Boolean)
                    .join(', '),
            },
            { label: 'Browser', value: iconProperties.find((p) => p.property === '$browser')?.label },
            {
                label: 'OS',
                value: iconProperties.find((p) => p.property === '$os' || p.property === '$os_name')?.label,
            },
            { label: 'Device', value: iconProperties.find((p) => p.property === '$device_type')?.label },
            { label: 'First URL', value: recording.start_url },
            { label: 'Referrer', value: recordingProperties?.['$entry_referring_domain'] },
        ].filter((detail) => !!detail.value)

        return (
            <DraggableToNotebook href={urls.replaySingle(recording.id)}>
                <div
                    data-quill
                    className={clsx(
                        'SessionRecordingPreview SessionRecordingPreview--compact group flex items-center gap-x-2 overflow-hidden cursor-pointer py-1.5 px-2 text-[11px] text-foreground',
                        isActive && 'SessionRecordingPreview--active'
                    )}
                >
                    {selectable && (
                        <span className="shrink-0 flex items-center">
                            <QuillItemCheckbox recording={recording} />
                        </span>
                    )}
                    {loading ? (
                        <Skeleton className="w-8 h-8 shrink-0 rounded" />
                    ) : (
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <div className="grid grid-cols-2 gap-0.5 p-0.5 w-8 h-8 shrink-0 rounded border border-border bg-muted ph-no-capture" />
                                }
                            >
                                {iconProperties.map(({ property, value }) => (
                                    <span
                                        key={property}
                                        className="flex items-center justify-center rounded-sm bg-card leading-none text-[11px]"
                                    >
                                        <PropertyIcon property={property} value={value} />
                                    </span>
                                ))}
                            </TooltipTrigger>
                            <TooltipContent side="right">
                                <div className="flex flex-col gap-0.5 text-xs">
                                    {tileDetails.map(({ label, value }) => (
                                        <span key={label} className="break-all">
                                            <span className="text-muted-foreground">{label}: </span>
                                            {value}
                                        </span>
                                    ))}
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    )}
                    <div className="grow min-w-0 flex flex-col gap-y-0.5">
                        <div className="flex items-center gap-x-1.5">
                            <span
                                className={clsx(
                                    'truncate grow text-xs ph-no-capture',
                                    recording.viewed ? 'font-medium' : 'font-semibold'
                                )}
                            >
                                {asDisplay(recording.person)}
                            </span>
                            {recording.matches_filters === false && (
                                <Tooltip>
                                    <TooltipTrigger render={<Badge variant="warning" className="shrink-0" />}>
                                        Doesn't match filters
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        This recording is listed only because it's open. It doesn't match the current
                                        filters.
                                    </TooltipContent>
                                </Tooltip>
                            )}
                            {playlistTimestampFormat === TimestampFormat.Relative ? (
                                <TZLabel
                                    className="text-muted-foreground shrink-0"
                                    time={recording.start_time}
                                    placement="right"
                                />
                            ) : (
                                <SimpleTimeLabel
                                    startTime={recording.start_time}
                                    timestampFormat={playlistTimestampFormat}
                                />
                            )}
                        </div>
                        <div className="flex items-center gap-x-2 text-muted-foreground">
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
                            <span className="grow" />
                            <SortMetric recording={recording} order={order} />
                        </div>
                        {isActive && recording.start_url && (
                            <span
                                title={`First URL: ${recording.start_url}`}
                                className="truncate text-muted-foreground ph-no-capture"
                            >
                                {recording.start_url.replace(/https?:\/\//g, '').split(/[?|#]/)[0]}
                            </span>
                        )}
                    </div>
                    <div className="min-w-4 flex flex-col items-center gap-y-1">
                        {recording.ongoing ? (
                            <Tooltip>
                                <TooltipTrigger render={<span className="inline-flex" />}>
                                    <IconLive className="animate-[pulse_1s_ease-out_infinite] text-primary-3000" />
                                </TooltipTrigger>
                                <TooltipContent>
                                    This recording is still ongoing - we received data within the last 5 minutes.
                                </TooltipContent>
                            </Tooltip>
                        ) : null}
                        {!recording.viewed ? (
                            <QuillUnwatchedIndicator otherViewersCount={recording.viewers?.length || 0} />
                        ) : null}
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
