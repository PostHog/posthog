import './SessionRecordingPreview.scss'

import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { IconBug, IconCursorClick, IconHourglass, IconKeyboard, IconLive } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS, SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS } from 'lib/constants'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { asDisplay } from 'scenes/persons/person-utils'
import { SimpleTimeLabel } from 'scenes/session-recordings/components/SimpleTimeLabel'
import { countryTitleFrom } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { TimestampFormat, playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { SessionRecordingType } from '~/types'

import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import {
    DEFAULT_RECORDING_FILTERS_ORDER_BY,
    MAX_SELECTED_RECORDINGS,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'

const ICON_CLASS_NAMES = 'text-secondary shrink-0'

export interface SessionRecordingPreviewProps {
    recording: SessionRecordingType
    isActive?: boolean
    /**
     * Whether to show a sessionRecordingPlaylistLogic selection checkbox on this preview.
     * @default false
     */
    selectable?: boolean
}

function RecordingDuration({ recordingDuration }: { recordingDuration: number | undefined }): JSX.Element {
    if (recordingDuration === undefined) {
        return <div className="flex text-secondary text-xs">-</div>
    }

    const formattedDuration = colonDelimitedDuration(recordingDuration)
    const [hours, minutes, seconds] = formattedDuration.split(':')

    return (
        <div className="flex text-secondary text-xs">
            {hours != '00' && <span>{hours}:</span>}
            <span>
                {minutes}:{seconds}
            </span>
        </div>
    )
}

function ErrorCount({ errorCount }: { errorCount: number | undefined }): JSX.Element {
    if (errorCount === undefined) {
        return <div className="flex items-center flex-1 justify-end font-semibold">-</div>
    }

    return (
        <div className="flex items-center flex-1 gap-x-1 justify-end font-semibold">
            <IconBug className={ICON_CLASS_NAMES} />
            <span>{errorCount}</span>
        </div>
    )
}

function RecordingExpiry({ recordingTtl }: { recordingTtl: number | undefined }): JSX.Element {
    if (recordingTtl === undefined) {
        return <div className="flex text-secondary text-xs">-</div>
    }

    const ttlColor = recordingTtl <= SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS ? '#f63b3bff' : 'currentColor'

    return (
        <div className="flex items-center gap-x-1 text-xs">
            <IconHourglass fill={ttlColor} className={ICON_CLASS_NAMES} />
            <span style={{ color: ttlColor }}>{recordingTtl}d</span>
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
            const value = property === '$device_type' ? deviceType : iconProperties[property]
            const label = property === '$geoip_country_code' ? countryTitleFrom(iconProperties) : value

            return { property, value, label }
        })
        .filter((property) => !!property.value)
}

export interface PropertyIconsProps {
    recordingProperties: GatheredProperty[]
    loading?: boolean
    iconClassNames?: string
}

export function PropertyIcons({ recordingProperties, loading, iconClassNames }: PropertyIconsProps): JSX.Element {
    return (
        <div className="flex gap-x-1 ph-no-capture items-center">
            {loading ? (
                <LemonSkeleton className="w-16 h-3" />
            ) : (
                recordingProperties.map(({ property, value, label }) => (
                    <Tooltip key={property} title={label}>
                        <span className="flex items-center gap-x-0.5">
                            <PropertyIcon className={iconClassNames} property={property} value={value} />
                            <span className="SessionRecordingPreview__property-label text-xs text-secondary">
                                {label}
                            </span>
                        </span>
                    </Tooltip>
                ))
            )}
        </div>
    )
}

function FirstURL(props: { startUrl: string | undefined }): JSX.Element {
    const firstPath = props.startUrl?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]
    return (
        <span className="flex overflow-hidden text-secondary text-xs">
            <span title={`First URL: ${props.startUrl}`} className="truncate">
                {firstPath}
            </span>
        </span>
    )
}

function RecordingOngoingIndicator(): JSX.Element {
    return (
        <Tooltip title="This recording is still ongoing - we received data within the last 5 minutes.">
            <IconLive className="animate-[pulse_1s_ease-out_infinite] text-primary-3000" />
        </Tooltip>
    )
}

export function UnwatchedIndicator({ otherViewersCount }: { otherViewersCount: number }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isExcludedFromHideRecordingsMenu = featureFlags[FEATURE_FLAGS.REPLAY_EXCLUDE_FROM_HIDE_RECORDINGS_MENU]

    const showSecondaryColor = !isExcludedFromHideRecordingsMenu && otherViewersCount > 0
    const nobodyWatched = !isExcludedFromHideRecordingsMenu && otherViewersCount === 0

    const tooltip = isExcludedFromHideRecordingsMenu
        ? 'You have not watched this recording yet.'
        : otherViewersCount
          ? `You have not watched this recording yet. ${otherViewersCount} other ${otherViewersCount === 1 ? 'person has' : 'people have'}.`
          : 'Nobody has watched this recording yet.'

    return (
        <Tooltip title={tooltip}>
            <div
                className={cn('w-2 h-2 rounded-full', showSecondaryColor ? 'bg-accent' : 'bg-danger')}
                aria-label={nobodyWatched ? 'unwatched-recording-by-everyone' : 'unwatched-recording-by-you'}
            />
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

function ItemCheckbox({ recording }: { recording: SessionRecordingType }): JSX.Element {
    const { selectedRecordingsIds } = useValues(sessionRecordingsPlaylistLogic)
    const { setSelectedRecordingsIds } = useActions(sessionRecordingsPlaylistLogic)

    return (
        <LemonCheckbox
            checked={selectedRecordingsIds.some((s) => s === recording.id)}
            data-attr="select-recording"
            aria-label="Select recording"
            disabledReason={
                selectedRecordingsIds.length >= MAX_SELECTED_RECORDINGS
                    ? `Cannot select more than ${MAX_SELECTED_RECORDINGS} recordings at once`
                    : undefined
            }
            onChange={() => {
                if (selectedRecordingsIds.some((r) => r === recording.id)) {
                    setSelectedRecordingsIds(selectedRecordingsIds.filter((r) => r !== recording.id))
                } else {
                    setSelectedRecordingsIds([...selectedRecordingsIds, recording.id])
                }
            }}
            stopPropagation
        />
    )
}

function ActivityMeta({ recording }: { recording: SessionRecordingType }): JSX.Element {
    return (
        <div className="flex items-center gap-1 text-secondary">
            <Tooltip className="flex items-center" title="Clicks">
                <span className="flex gap-x-0.5 items-center">
                    <IconCursorClick className={ICON_CLASS_NAMES} />
                    <span>{recording.click_count}</span>
                    <span className="SessionRecordingPreview__activity-label">clicks</span>
                </span>
            </Tooltip>
            <Tooltip className="flex items-center" title="Key presses">
                <span className="flex gap-x-0.5 items-center">
                    <IconKeyboard className={ICON_CLASS_NAMES} />
                    <span>{recording.keypress_count}</span>
                    <span className="SessionRecordingPreview__activity-label">key presses</span>
                </span>
            </Tooltip>
        </div>
    )
}

export const SessionRecordingPreview = memo(
    function SessionRecordingPreview({
        recording,
        isActive,
        selectable = false,
    }: SessionRecordingPreviewProps): JSX.Element {
        const { playlistTimestampFormat } = useValues(playerSettingsLogic)

        const { filters } = useValues(sessionRecordingsPlaylistLogic)
        const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)

        const recordingProperties = recordingPropertiesById[recording.id]
        const loading = !recordingProperties && recordingPropertiesLoading
        const iconProperties = gatherIconProperties(recordingProperties, recording)
        const order = filters.order || DEFAULT_RECORDING_FILTERS_ORDER_BY

        return (
            <DraggableToNotebook href={urls.replaySingle(recording.id)}>
                <div
                    key={recording.id}
                    className={cn(
                        'flex overflow-hidden cursor-pointer py-0.5 px-1 text-xs border-l-3 hover:bg-accent-highlight-secondary',
                        isActive ? 'border-l-accent' : 'border-l-transparent'
                    )}
                >
                    {selectable && <ItemCheckbox recording={recording} />}
                    <div className="grow overflow-hidden flex flex-col gap-y-2 ml-1">
                        <div className="flex items-center justify-between gap-x-0.5">
                            <div className="flex overflow-hidden font-medium ph-no-capture">
                                <span className="truncate">{asDisplay(recording.person)}</span>
                            </div>
                            {playlistTimestampFormat === TimestampFormat.Relative ? (
                                <TZLabel
                                    className="overflow-hidden text-ellipsis text-xs text-secondary shrink-0"
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

                        <div className="flex justify-between items-center gap-x-0.5">
                            <div className="flex items-center gap-x-4 text-secondary text-sm">
                                <PropertyIcons
                                    recordingProperties={iconProperties}
                                    iconClassNames={ICON_CLASS_NAMES}
                                    loading={loading}
                                />
                                <ActivityMeta recording={recording} />
                            </div>

                            {order === 'console_error_count' ? (
                                <ErrorCount errorCount={recording.console_error_count} />
                            ) : order === 'recording_ttl' ? (
                                <RecordingExpiry recordingTtl={recording.recording_ttl} />
                            ) : (
                                <RecordingDuration recordingDuration={durationToShow(recording, order)} />
                            )}
                        </div>

                        <FirstURL startUrl={recording.start_url} />
                    </div>

                    <div
                        className={cn(
                            'min-w-6 flex flex-col gap-x-0.5 items-center',
                            recording.ongoing ? 'mt-1' : 'mt-2'
                        )}
                    >
                        {recording.ongoing ? <RecordingOngoingIndicator /> : null}
                        {!recording.viewed ? (
                            <UnwatchedIndicator otherViewersCount={recording.viewers?.length || 0} />
                        ) : null}
                    </div>
                </div>
            </DraggableToNotebook>
        )
    },
    (prevProps, nextProps) =>
        prevProps.recording.id === nextProps.recording.id &&
        prevProps.isActive === nextProps.isActive &&
        prevProps.selectable === nextProps.selectable
)

export function SessionRecordingPreviewSkeleton(): JSX.Element {
    return (
        <div className="p-4 flex flex-col gap-y-2">
            <LemonSkeleton className="w-1/2 h-4" />
            <LemonSkeleton className="w-1/3 h-4" />
        </div>
    )
}
