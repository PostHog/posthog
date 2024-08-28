import { IconBug, IconCursorClick, IconKeyboard, IconMagicWand, IconPinFilled } from '@posthog/icons'
import clsx from 'clsx'
import { useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
import { useState } from 'react'
import { countryCodeToName } from 'scenes/insights/views/WorldMap'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { asDisplay } from 'scenes/persons/person-utils'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { DurationType, SessionRecordingType } from '~/types'

import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

export interface SessionRecordingPreviewProps {
    recording: SessionRecordingType
    isActive?: boolean
    onClick?: () => void
    pinned?: boolean
    summariseFn?: (recording: SessionRecordingType) => void
    sessionSummaryLoading?: boolean
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

function ViewedIndicator(): JSX.Element {
    return (
        <Tooltip title="Indicates the recording has not been watched yet">
            <div className="w-2 h-2 rounded-full bg-primary-3000" aria-label="unwatched-recording-label" />
        </Tooltip>
    )
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
    pinned,
    summariseFn,
    sessionSummaryLoading,
}: SessionRecordingPreviewProps): JSX.Element {
    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)
    const { durationTypeToShow } = useValues(playerSettingsLogic)

    const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)
    const recordingProperties = recordingPropertiesById[recording.id]
    const loading = !recordingProperties && recordingPropertiesLoading
    const iconProperties = gatherIconProperties(recordingProperties, recording)

    const iconClassNames = 'text-muted-alt shrink-0'

    const [summaryPopoverIsVisible, setSummaryPopoverIsVisible] = useState<boolean>(false)

    const [summaryButtonIsVisible, setSummaryButtonIsVisible] = useState<boolean>(false)

    return (
        <DraggableToNotebook href={urls.replaySingle(recording.id)}>
            <div
                key={recording.id}
                className={clsx(
                    'SessionRecordingPreview flex overflow-hidden cursor-pointer py-1.5 pl-2',
                    isActive && 'SessionRecordingPreview--active'
                )}
                onClick={() => onClick?.()}
                onMouseEnter={() => setSummaryButtonIsVisible(true)}
                onMouseLeave={() => setSummaryButtonIsVisible(false)}
            >
                <FlaggedFeature flag={FEATURE_FLAGS.AI_SESSION_SUMMARY} match={true}>
                    {summariseFn && (
                        <Popover
                            showArrow={true}
                            visible={summaryPopoverIsVisible && summaryButtonIsVisible}
                            placement="right"
                            onClickOutside={() => setSummaryPopoverIsVisible(false)}
                            overlay={
                                sessionSummaryLoading ? (
                                    <Spinner />
                                ) : (
                                    <div className="text-xl max-w-auto lg:max-w-3/5">{recording.summary}</div>
                                )
                            }
                        >
                            <LemonButton
                                size="small"
                                type="primary"
                                className={clsx(
                                    summaryButtonIsVisible ? 'block' : 'hidden',
                                    'absolute right-px top-px'
                                )}
                                icon={<IconMagicWand />}
                                onClick={(e) => {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    setSummaryPopoverIsVisible(!summaryPopoverIsVisible)
                                    if (!recording.summary) {
                                        summariseFn(recording)
                                    }
                                }}
                            />
                        </Popover>
                    )}
                </FlaggedFeature>
                <div className="grow overflow-hidden space-y-1">
                    <div className="flex items-center justify-between gap-2">
                        <div className="flex overflow-hidden font-medium text-link ph-no-capture">
                            <span className="truncate">{asDisplay(recording.person)}</span>
                        </div>

                        <TZLabel
                            className="overflow-hidden text-ellipsis text-xs text-muted shrink-0"
                            time={recording.start_time}
                            placement="right"
                        />
                    </div>

                    <div className="flex items-center justify-between items-center gap-2">
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

                        {orderBy === 'console_error_count' ? (
                            <ErrorCount iconClassNames={iconClassNames} errorCount={recording.console_error_count} />
                        ) : (
                            <RecordingDuration
                                recordingDuration={durationToShow(
                                    recording,
                                    orderBy === 'start_time' ? durationTypeToShow : orderBy
                                )}
                            />
                        )}
                    </div>

                    <FirstURL startUrl={recording.start_url} />
                </div>

                <div className="min-w-6 flex flex-col items-center mt-2">
                    {!recording.viewed ? <ViewedIndicator /> : null}
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
