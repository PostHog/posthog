import { IconBug, IconCursorClick, IconKeyboard, IconLive, IconPinFilled } from '@posthog/icons'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
import { countryCodeToName } from 'scenes/insights/views/WorldMap'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { asDisplay } from 'scenes/persons/person-utils'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import { playerSettingsLogic, TimestampFormat } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { RecordingsQuery } from '~/queries/schema'
import { SessionRecordingType } from '~/types'

import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import { DEFAULT_RECORDING_FILTERS_ORDER_BY, sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export interface SessionRecordingPreviewProps {
    recording: SessionRecordingType
    isActive?: boolean
    onClick?: () => void
    pinned?: boolean
}

function RecordingDuration({ recordingDuration }: { recordingDuration: number | undefined }): JSX.Element {
    if (recordingDuration === undefined) {
        return <div className="flex text-muted text-xs">-</div>
    }

    const formattedDuration = colonDelimitedDuration(recordingDuration)
    const [hours, minutes, seconds] = formattedDuration.split(':')

    return (
        <div className="flex text-muted text-xs">
            {hours != '00' && <span>{hours}:</span>}
            <span>
                {minutes}:{seconds}
            </span>
        </div>
    )
}

function ErrorCount({
    iconClassNames,
    errorCount,
}: {
    iconClassNames: string
    errorCount: number | undefined
}): JSX.Element {
    if (errorCount === undefined) {
        return <div className="flex items-center flex-1 justify-end font-semibold">-</div>
    }

    return (
        <div className="flex items-center flex-1 space-x-1 justify-end font-semibold">
            <IconBug className={iconClassNames} />
            <span>{errorCount}</span>
        </div>
    )
}

interface GatheredProperty {
    property: string
    value: string | undefined
    label: string | undefined
}

const browserIconPropertyKeys = ['$geoip_country_code', '$browser', '$device_type', '$os']
const mobileIconPropertyKeys = ['$geoip_country_code', '$device_type', '$os_name']

export function gatherIconProperties(
    recordingProperties: Record<string, any> | undefined,
    recording?: SessionRecordingType
): GatheredProperty[] {
    const iconProperties =
        recordingProperties && Object.keys(recordingProperties).length > 0
            ? recordingProperties
            : recording?.person?.properties || {}

    const deviceType = iconProperties['$device_type'] || iconProperties['$initial_device_type']
    const iconPropertyKeys = deviceType === 'Mobile' ? mobileIconPropertyKeys : browserIconPropertyKeys

    return iconPropertyKeys
        .flatMap((property) => {
            let value = iconProperties?.[property]
            const label = value
            if (property === '$device_type') {
                value = iconProperties?.['$device_type'] || iconProperties?.['$initial_device_type']
            }

            return { property, value, label }
        })
        .filter((property) => !!property.value)
}

export interface PropertyIconsProps {
    recordingProperties: GatheredProperty[]
    loading?: boolean
    iconClassNames?: string
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export function PropertyIcons({ recordingProperties, loading, iconClassNames }: PropertyIconsProps): JSX.Element {
    return (
        <div className="flex space-x-1 ph-no-capture">
            {loading ? (
                <LemonSkeleton className="w-16 h-3" />
            ) : (
                recordingProperties.map(({ property, value, label }) => (
                    <Tooltip
                        key={property}
                        title={label && property === '$geoip_country_code' ? countryCodeToName[label] : label}
                    >
                        <PropertyIcon className={iconClassNames} property={property} value={value} />
                    </Tooltip>
                ))
            )}
        </div>
    )
}

function FirstURL(props: { startUrl: string | undefined }): JSX.Element {
    const firstPath = props.startUrl?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]
    return (
        <span className="flex overflow-hidden text-muted text-xs">
            <span title={`First URL: ${props.startUrl}`} className="truncate">
                {firstPath}
            </span>
        </span>
    )
}

function PinnedIndicator(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'
    const description = isTestingSaved ? 'saved' : 'pinned'
    return (
        <Tooltip placement="top-end" title={<>This recording is {description} to this list.</>}>
            <IconPinFilled className="text-sm text-orange shrink-0" />
        </Tooltip>
    )
}

function RecordingOngoingIndicator(): JSX.Element {
    return (
        <Tooltip title="This recording is still ongoing - we received data within the last 5 minutes.">
            <IconLive className="animate-[pulse_1s_ease-out_infinite] text-primary-3000" />
        </Tooltip>
    )
}

function UnwatchedIndicator(): JSX.Element {
    return (
        <Tooltip title="Indicates the recording has not been watched yet">
            <div className="w-2 h-2 rounded-full bg-primary-3000" aria-label="unwatched-recording-label" />
        </Tooltip>
    )
}

function durationToShow(recording: SessionRecordingType, order: RecordingsQuery['order']): number | undefined {
    return order === 'active_seconds'
        ? recording.active_seconds
        : order === 'inactive_seconds'
        ? recording.inactive_seconds
        : recording.recording_duration
}

export function SessionRecordingPreview({
    recording,
    isActive,
    onClick,
    pinned,
}: SessionRecordingPreviewProps): JSX.Element {
    const { playlistTimestampFormat } = useValues(playerSettingsLogic)

    const { filters } = useValues(sessionRecordingsPlaylistLogic)
    const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)

    const recordingProperties = recordingPropertiesById[recording.id]
    const loading = !recordingProperties && recordingPropertiesLoading
    const iconProperties = gatherIconProperties(recordingProperties, recording)

    const iconClassNames = 'text-muted-alt shrink-0'

    return (
        <DraggableToNotebook href={urls.replaySingle(recording.id)}>
            <div
                key={recording.id}
                className={clsx(
                    'SessionRecordingPreview flex overflow-hidden cursor-pointer py-0.5 px-1 text-xs',
                    isActive && 'SessionRecordingPreview--active'
                )}
                onClick={() => onClick?.()}
            >
                <div className="grow overflow-hidden space-y-0.5">
                    <div className="flex items-center justify-between gap-0.5">
                        <div className="flex overflow-hidden font-medium text-link ph-no-capture">
                            <span className="truncate">{asDisplay(recording.person)}</span>
                        </div>

                        {playlistTimestampFormat === TimestampFormat.Relative ? (
                            <TZLabel
                                className="overflow-hidden text-ellipsis text-xs text-muted shrink-0"
                                time={recording.start_time}
                                placement="right"
                            />
                        ) : playlistTimestampFormat === TimestampFormat.UTC ? (
                            <SimpleTimeLabel startTime={recording.start_time} isUTC={true} />
                        ) : (
                            <SimpleTimeLabel startTime={recording.start_time} isUTC={false} />
                        )}
                    </div>

                    <div className="flex justify-between items-center gap-0.5">
                        <div className="flex space-x-2 text-muted text-xs">
                            <PropertyIcons
                                recordingProperties={iconProperties}
                                iconClassNames={iconClassNames}
                                loading={loading}
                            />

                            <div className="flex gap-1">
                                <Tooltip className="flex items-center" title="Clicks">
                                    <span className="space-x-0.5">
                                        <IconCursorClick className={iconClassNames} />
                                        <span>{recording.click_count}</span>
                                    </span>
                                </Tooltip>
                                <Tooltip className="flex items-center" title="Key presses">
                                    <span className="space-x-0.5">
                                        <IconKeyboard className={iconClassNames} />
                                        <span>{recording.keypress_count}</span>
                                    </span>
                                </Tooltip>
                            </div>
                        </div>

                        {filters.order === 'console_error_count' ? (
                            <ErrorCount iconClassNames={iconClassNames} errorCount={recording.console_error_count} />
                        ) : (
                            <RecordingDuration
                                recordingDuration={durationToShow(
                                    recording,
                                    filters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY
                                )}
                            />
                        )}
                    </div>

                    <FirstURL startUrl={recording.start_url} />
                </div>

                <div
                    className={clsx(
                        'min-w-6 flex flex-col gap-0.5 items-center',
                        // need different margin if the first item is an icon
                        recording.ongoing || pinned ? 'mt-1' : 'mt-2'
                    )}
                >
                    {recording.ongoing ? <RecordingOngoingIndicator /> : null}
                    {pinned ? <PinnedIndicator /> : null}
                    {!recording.viewed ? <UnwatchedIndicator /> : null}
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
