import { DurationType, SessionRecordingType } from '~/types'
import { colonDelimitedDuration } from 'lib/utils'
import clsx from 'clsx'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { IconAutocapture, IconKeyboard, IconPinFilled, IconSchedule } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { urls } from 'scenes/urls'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { useValues } from 'kea'
import { asDisplay } from 'scenes/persons/person-utils'
import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'

export interface SessionRecordingPreviewProps {
    recording: SessionRecordingType
    onPropertyClick?: (property: string, value?: string) => void
    isActive?: boolean
    onClick?: () => void
    pinned?: boolean
}

function RecordingDuration({
    iconClassNames,
    recordingDuration,
}: {
    iconClassNames: string
    recordingDuration: number | undefined
}): JSX.Element {
    if (recordingDuration === undefined) {
        return <div className="flex items-center flex-1 justify-end font-semibold">-</div>
    }

    const formattedDuration = colonDelimitedDuration(recordingDuration)
    const [hours, minutes, seconds] = formattedDuration.split(':')

    return (
        <div className="flex items-center flex-1 justify-end font-semibold">
            <IconSchedule className={iconClassNames} />
            <span>
                <span className={clsx(hours === '00' && 'opacity-50 font-normal')}>{hours}:</span>
                <span
                    className={clsx({
                        'opacity-50 font-normal': hours === '00' && minutes === '00',
                    })}
                >
                    {minutes}:
                </span>
                {seconds}
            </span>
        </div>
    )
}

function ActivityIndicators({
    recording,
    onPropertyClick,
    iconClassnames,
}: {
    recording: SessionRecordingType
    onPropertyClick?: (property: string, value?: string) => void
    iconClassnames: string
}): JSX.Element {
    const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)

    const recordingProperties = recordingPropertiesById[recording.id]
    const loading = !recordingProperties && recordingPropertiesLoading

    const iconPropertyKeys = ['$geoip_country_code', '$browser', '$device_type', '$os']
    const iconProperties =
        recordingProperties && Object.keys(recordingProperties).length > 0
            ? recordingProperties
            : recording.person?.properties || {}

    const propertyIcons = (
        <div className="flex flex-row flex-nowrap shrink-0 gap-1 h-6 ph-no-capture">
            {!loading ? (
                iconPropertyKeys.map((property) => {
                    let value = iconProperties?.[property]
                    if (property === '$device_type') {
                        value = iconProperties?.['$device_type'] || iconProperties?.['$initial_device_type']
                    }

                    let tooltipValue = value
                    if (property === '$geoip_country_code') {
                        tooltipValue = `${iconProperties?.['$geoip_country_name']} (${value})`
                    }

                    return (
                        <PropertyIcon
                            key={property}
                            onClick={(e) => {
                                if (e.altKey) {
                                    e.stopPropagation()
                                    onPropertyClick?.(property, value)
                                }
                            }}
                            className={iconClassnames}
                            property={property}
                            value={value}
                            tooltipTitle={() => (
                                <div className="text-center">
                                    <code>Alt + Click</code> to filter for
                                    <br />
                                    <span className="font-medium">{tooltipValue ?? 'N/A'}</span>
                                </div>
                            )}
                        />
                    )
                })
            ) : (
                <LemonSkeleton className="w-18 h-4 my-1" />
            )}
        </div>
    )

    return (
        <div className="flex iems-center gap-2 text-xs text-muted-alt">
            {propertyIcons}

            <span
                title={`Click count: ${recording.click_count}`}
                className="flex items-center gap-1  overflow-hidden shrink-0"
            >
                <IconAutocapture />
                {recording.click_count}
            </span>

            <span
                title={`Keyboard inputs: ${recording.keypress_count}`}
                className="flex items-center gap-1  overflow-hidden shrink-0"
            >
                <IconKeyboard />
                {recording.keypress_count}
            </span>
        </div>
    )
}

function FirstURL(props: { startUrl: string | undefined }): JSX.Element {
    const firstPath = props.startUrl?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]
    return (
        <div className="flex items-center justify-between gap-4 w-2/3">
            <span className="flex items-center gap-1 overflow-hidden text-muted text-xs">
                <span title={`First URL: ${props.startUrl}`} className="truncate">
                    {firstPath}
                </span>
            </span>
        </div>
    )
}

function PinnedIndicator(): JSX.Element | null {
    return (
        <Tooltip placement="topRight" title={`This recording is pinned to this list.`}>
            <IconPinFilled className="text-sm text-orange shrink-0" />
        </Tooltip>
    )
}

function ViewedIndicator(props: { viewed: boolean }): JSX.Element | null {
    return !props.viewed ? (
        <Tooltip title={'Indicates the recording has not been watched yet'}>
            <div className="w-2 h-2 m-1 rounded-full bg-primary-3000" aria-label="unwatched-recording-label" />
        </Tooltip>
    ) : null
}

function durationToShow(recording: SessionRecordingType, durationType: DurationType | undefined): number | undefined {
    return {
        duration: recording.recording_duration,
        active_seconds: recording.active_seconds,
        inactive_seconds: recording.inactive_seconds,
    }[durationType || 'duration']
}

export function SessionRecordingPreview({
    recording,
    isActive,
    onClick,
    onPropertyClick,
    pinned,
}: SessionRecordingPreviewProps): JSX.Element {
    const { durationTypeToShow } = useValues(playerSettingsLogic)

    const iconClassnames = clsx('SessionRecordingPreview__property-icon text-base text-muted-alt')

    return (
        <DraggableToNotebook href={urls.replaySingle(recording.id)}>
            <div
                key={recording.id}
                className={clsx('SessionRecordingPreview', isActive && 'SessionRecordingPreview--active')}
                onClick={() => onClick?.()}
            >
                <div className="grow overflow-hidden space-y-px">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1 shrink overflow-hidden">
                            <div className="truncate font-medium text-link ph-no-capture">
                                {asDisplay(recording.person)}
                            </div>
                        </div>
                        <div className="flex-1" />

                        <RecordingDuration
                            iconClassNames={iconClassnames}
                            recordingDuration={durationToShow(recording, durationTypeToShow)}
                        />
                    </div>

                    <div className="flex items-center justify-between gap-2">
                        <ActivityIndicators
                            onPropertyClick={onPropertyClick}
                            recording={recording}
                            iconClassnames={iconClassnames}
                        />
                        <TZLabel
                            className="overflow-hidden text-ellipsis text-xs"
                            time={recording.start_time}
                            placement="right"
                        />
                    </div>

                    <FirstURL startUrl={recording.start_url} />
                </div>

                <div className="w-6 flex flex-col items-center mt-1">
                    <ViewedIndicator viewed={recording.viewed} />
                    {pinned ? <PinnedIndicator /> : null}
                </div>
            </div>
        </DraggableToNotebook>
    )
}

export function SessionRecordingPreviewSkeleton(): JSX.Element {
    return (
        <div className="p-4 space-y-2">
            <LemonSkeleton className="w-1/2 h-4" />
            <LemonSkeleton className="w-1/3 h-4" />
        </div>
    )
}
