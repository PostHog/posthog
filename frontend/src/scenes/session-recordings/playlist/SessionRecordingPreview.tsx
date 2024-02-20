import clsx from 'clsx'
import { useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAutoAwesome, IconAutocapture, IconKeyboard, IconPinFilled, IconSchedule } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
import { Fragment, useState } from 'react'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { asDisplay } from 'scenes/persons/person-utils'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { urls } from 'scenes/urls'

import { DurationType, SessionRecordingType } from '~/types'

import { sessionRecordingsListPropertiesLogic } from './sessionRecordingsListPropertiesLogic'

export interface SessionRecordingPreviewProps {
    recording: SessionRecordingType
    onPropertyClick?: (property: string, value?: string) => void
    isActive?: boolean
    onClick?: () => void
    pinned?: boolean
    summariseFn?: (recording: SessionRecordingType) => void
    sessionSummaryLoading?: boolean
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

interface GatheredProperty {
    property: string
    value: string | undefined
    label: string | undefined
    tooltipValue: string
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

    return iconPropertyKeys.flatMap((property) => {
        let value = iconProperties?.[property]
        let label = value
        if (property === '$device_type') {
            value = iconProperties?.['$device_type'] || iconProperties?.['$initial_device_type']
        }

        let tooltipValue = value
        if (property === '$geoip_country_code') {
            tooltipValue = `${iconProperties?.['$geoip_country_name']} (${value})`
            label = [iconProperties?.['$geoip_city_name'], iconProperties?.['$geoip_subdivision_1_code']]
                .filter(Boolean)
                .join(', ')
        }
        return { property, value, tooltipValue, label }
    })
}

export interface PropertyIconsProps {
    recordingProperties: GatheredProperty[]
    loading?: boolean
    onPropertyClick?: (property: string, value?: string) => void
    iconClassnames?: string
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export function PropertyIcons({
    recordingProperties,
    loading,
    onPropertyClick,
    iconClassnames,
    showTooltip = true,
    showLabel = undefined,
}: PropertyIconsProps): JSX.Element {
    return (
        <div className="flex flex-row flex-nowrap shrink-0 gap-1 h-6 ph-no-capture items-center">
            {loading ? (
                <LemonSkeleton className="w-18 h-4 my-1" />
            ) : (
                recordingProperties.map(({ property, value, tooltipValue, label }) => {
                    return (
                        <Fragment key={property}>
                            <PropertyIcon
                                onClick={(e) => {
                                    if (e.altKey) {
                                        e.stopPropagation()
                                        onPropertyClick?.(property, value)
                                    }
                                }}
                                className={iconClassnames}
                                property={property}
                                value={value}
                                noTooltip={!showTooltip}
                                tooltipTitle={() => (
                                    <div className="text-center">
                                        <code>Alt + Click</code> to filter for
                                        <br />
                                        <span className="font-medium">{tooltipValue ?? 'N/A'}</span>
                                    </div>
                                )}
                            />
                            {showLabel?.(property) && <span className="text-xs text-muted-alt">{label || value}</span>}
                        </Fragment>
                    )
                })
            )}
        </div>
    )
}

function ActivityIndicators({
    recording,
    ...props
}: {
    recording: SessionRecordingType
    onPropertyClick?: (property: string, value?: string) => void
    iconClassnames: string
}): JSX.Element {
    const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)
    const recordingProperties = recordingPropertiesById[recording.id]
    const loading = !recordingProperties && recordingPropertiesLoading
    const iconProperties = gatherIconProperties(recordingProperties, recording)

    return (
        <div className="flex iems-center gap-2 text-xs text-muted-alt">
            <PropertyIcons recordingProperties={iconProperties} loading={loading} {...props} />

            <span
                title={`Mouse clicks: ${recording.click_count}`}
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
    const { featureFlags } = useValues(featureFlagLogic)
    const isTestingSaved = featureFlags[FEATURE_FLAGS.SAVED_NOT_PINNED] === 'test'
    const description = isTestingSaved ? 'saved' : 'pinned'
    return (
        <Tooltip placement="topRight" title={<>This recording is {description} to this list.</>}>
            <IconPinFilled className="text-sm text-orange shrink-0" />
        </Tooltip>
    )
}

function ViewedIndicator(props: { viewed: boolean }): JSX.Element | null {
    return !props.viewed ? (
        <Tooltip title="Indicates the recording has not been watched yet">
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
    summariseFn,
    sessionSummaryLoading,
}: SessionRecordingPreviewProps): JSX.Element {
    const { durationTypeToShow } = useValues(playerSettingsLogic)

    const iconClassnames = clsx('SessionRecordingPreview__property-icon text-base text-muted-alt')

    const [summaryPopoverIsVisible, setSummaryPopoverIsVisible] = useState<boolean>(false)

    const [summaryButtonIsVisible, setSummaryButtonIsVisible] = useState<boolean>(false)

    return (
        <DraggableToNotebook href={urls.replaySingle(recording.id)}>
            <div
                key={recording.id}
                className={clsx('SessionRecordingPreview', isActive && 'SessionRecordingPreview--active')}
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
                                icon={<IconAutoAwesome />}
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
