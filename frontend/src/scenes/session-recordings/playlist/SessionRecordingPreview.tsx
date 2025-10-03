import './SessionRecordingPreview.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { memo } from 'react'

import { IconBug, IconCursorClick, IconKeyboard, IconLive } from '@posthog/icons'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
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
        <div className="flex items-center flex-1 deprecated-space-x-1 justify-end font-semibold">
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
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export function PropertyIcons({ recordingProperties, loading, iconClassNames }: PropertyIconsProps): JSX.Element {
    return (
        <div className="flex deprecated-space-x-1 ph-no-capture">
            {loading ? (
                <LemonSkeleton className="w-16 h-3" />
            ) : (
                recordingProperties.map(({ property, value, label }) => (
                    <Tooltip key={property} title={label}>
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

    // If person wished to be excluded from the hide recordings menu, we don't show the tooltip
    const tooltip = isExcludedFromHideRecordingsMenu ? (
        <span>You have not watched this recording yet.</span>
    ) : otherViewersCount ? (
        <span>
            You have not watched this recording yet. {otherViewersCount} other{' '}
            {otherViewersCount === 1 ? 'person has' : 'people have'}.
        </span>
    ) : (
        <span>Nobody has watched this recording yet.</span>
    )

    return (
        <Tooltip title={tooltip}>
            <div
                className={clsx(
                    'UnwatchedIndicator w-2 h-2 rounded-full',
                    isExcludedFromHideRecordingsMenu
                        ? 'UnwatchedIndicator--primary'
                        : otherViewersCount
                          ? 'UnwatchedIndicator--secondary'
                          : 'UnwatchedIndicator--primary'
                )}
                aria-label={
                    isExcludedFromHideRecordingsMenu
                        ? 'unwatched-recording-by-you-label'
                        : otherViewersCount
                          ? 'unwatched-recording-by-you-label'
                          : 'unwatched-recording-by-everyone-label'
                }
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

        const iconClassNames = 'text-secondary shrink-0'

        return (
            <DraggableToNotebook href={urls.replaySingle(recording.id)}>
                <div
                    key={recording.id}
                    className={clsx(
                        'SessionRecordingPreview flex overflow-hidden cursor-pointer py-0.5 px-1 text-xs',
                        isActive && 'SessionRecordingPreview--active'
                    )}
                >
                    {selectable && <ItemCheckbox recording={recording} />}
                    <div className="grow overflow-hidden deprecated-space-y-1 ml-1">
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
                            <div className="flex deprecated-space-x-2 text-secondary text-sm">
                                <PropertyIcons
                                    recordingProperties={iconProperties}
                                    iconClassNames={iconClassNames}
                                    loading={loading}
                                />

                                <div className="flex gap-1">
                                    <Tooltip className="flex items-center" title="Clicks">
                                        <span className="flex gap-x-0.5">
                                            <IconCursorClick className={iconClassNames} />
                                            <span>{recording.click_count}</span>
                                        </span>
                                    </Tooltip>
                                    <Tooltip className="flex items-center" title="Key presses">
                                        <span className="flex gap-x-0.5">
                                            <IconKeyboard className={iconClassNames} />
                                            <span>{recording.keypress_count}</span>
                                        </span>
                                    </Tooltip>
                                </div>
                            </div>

                            {filters.order === 'console_error_count' ? (
                                <ErrorCount
                                    iconClassNames={iconClassNames}
                                    errorCount={recording.console_error_count}
                                />
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
                            'min-w-6 flex flex-col gap-x-0.5 items-center',
                            // need different margin if the first item is an icon
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
        <div className="p-4 deprecated-space-y-2">
            <LemonSkeleton className="w-1/2 h-4" />
            <LemonSkeleton className="w-1/3 h-4" />
        </div>
    )
}
