import {
    IconBug,
    IconCalendar,
    IconCursorClick,
    IconKeyboard,
    IconMagicWand,
    IconPinFilled,
    IconTerminal,
} from '@posthog/icons'
import { LemonDivider, LemonDropdown, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconLink } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { colonDelimitedDuration } from 'lib/utils'
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
            {minutes != '00' && <span>{minutes}:</span>}
            {seconds}
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
    iconClassNames?: string
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export function PropertyIcons({
    recordingProperties,
    loading,
    onPropertyClick,
    iconClassNames,
    showTooltip = true,
}: PropertyIconsProps): JSX.Element {
    return (
        <div className="grid grid-cols-2 gap-x-12 gap-y-1 ph-no-capture">
            {loading ? (
                <LemonSkeleton className="w-18 h-4 my-1" />
            ) : (
                recordingProperties.map(({ property, value, tooltipValue, label }) => (
                    <div className="flex items-center" key={property}>
                        <PropertyIcon
                            onClick={(e) => {
                                if (e.altKey) {
                                    e.stopPropagation()
                                    onPropertyClick?.(property, value)
                                }
                            }}
                            className={iconClassNames}
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
                        <span>{label || value}</span>
                    </div>
                ))
            )}
        </div>
    )
}

function FirstURL(props: { startUrl: string | undefined }): JSX.Element {
    const firstPath = props.startUrl?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]
    return (
        <div className="flex items-center justify-between gap-4 w-3/5">
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
        <Tooltip placement="top-end" title={<>This recording is {description} to this list.</>}>
            <IconPinFilled className="text-sm text-orange shrink-0" />
        </Tooltip>
    )
}

function ViewedIndicator({ viewed }: { viewed: boolean }): JSX.Element | null {
    return !viewed ? (
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
    pinned,
    summariseFn,
    sessionSummaryLoading,
}: SessionRecordingPreviewProps): JSX.Element {
    const { orderBy } = useValues(sessionRecordingsPlaylistLogic)
    const { durationTypeToShow, showRecordingListPreviews } = useValues(playerSettingsLogic)

    const iconClassnames = 'text-base text-muted-alt'

    const innerContent = (
        <div
            key={recording.id}
            className={clsx(
                'SessionRecordingPreview flex gap-1 overflow-hidden cursor-pointer py-1.5 pl-2',
                isActive && 'SessionRecordingPreview--active'
            )}
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

                    <TZLabel
                        className="overflow-hidden text-ellipsis text-xs text-muted"
                        time={recording.start_time}
                        placement="right"
                        showPopover={false}
                    />
                </div>

                <div className="flex items-center justify-between gap-2">
                    <FirstURL startUrl={recording.start_url} />

                    {orderBy === 'console_error_count' ? (
                        <ErrorCount iconClassNames={iconClassnames} errorCount={recording.console_error_count} />
                    ) : (
                        <RecordingDuration
                            recordingDuration={durationToShow(
                                recording,
                                orderBy === 'start_time' ? durationTypeToShow : orderBy
                            )}
                        />
                    )}
                </div>
            </div>

            <div className="w-6 flex flex-col items-center mt-1">
                <ViewedIndicator viewed={recording.viewed} />
                {pinned ? <PinnedIndicator /> : null}
            </div>
        </div>
    )

    return (
        <DraggableToNotebook href={urls.replaySingle(recording.id)}>
            {showRecordingListPreviews ? (
                <LemonDropdown
                    placement="right-start"
                    trigger="hover"
                    overlay={
                        <SessionRecordingPreviewPopover
                            recording={recording}
                            summariseFn={summariseFn}
                            sessionSummaryLoading={sessionSummaryLoading}
                        />
                    }
                >
                    {innerContent}
                </LemonDropdown>
            ) : (
                innerContent
            )}
        </DraggableToNotebook>
    )
}

function SessionRecordingPreviewPopover({
    recording,
    summariseFn,
    sessionSummaryLoading,
}: {
    recording: SessionRecordingType
    summariseFn?: (recording: SessionRecordingType) => void
    sessionSummaryLoading?: boolean
}): JSX.Element {
    const { recordingPropertiesById, recordingPropertiesLoading } = useValues(sessionRecordingsListPropertiesLogic)
    const recordingProperties = recordingPropertiesById[recording.id]
    const loading = !recordingProperties && recordingPropertiesLoading
    const iconProperties = gatherIconProperties(recordingProperties, recording)

    const iconClassNames = 'text-muted-alt mr-2 shrink-0'

    return (
        <div className="max-w-80">
            <div className="gap-1 px-2">
                <h3>Session data</h3>

                <PropertyIcons recordingProperties={iconProperties} iconClassNames={iconClassNames} loading={loading} />

                <div className="flex items-center">
                    <IconLink className={iconClassNames} />
                    <Link to={recording.start_url} target="_blank" className="truncate">
                        {recording.start_url}
                    </Link>
                </div>

                <div className="flex items-center">
                    <IconCalendar className={iconClassNames} />
                    <TZLabel
                        time={recording.start_time}
                        formatDate="MMMM DD, YYYY"
                        formatTime="h:mm A"
                        showPopover={false}
                    />
                </div>
            </div>

            <LemonDivider className="" />

            <div className="gap-1 px-2">
                <h3>Activity</h3>

                <div className="flex items-center">
                    <IconCursorClick className={iconClassNames} />
                    <span>{recording.click_count} clicks</span>
                </div>
                <div className="flex items-center">
                    <IconKeyboard className={iconClassNames} />
                    <span>{recording.keypress_count} key presses</span>
                </div>
                <div className="flex items-center">
                    <IconTerminal className={iconClassNames} />
                    <span>{recording.console_error_count} console errors</span>
                </div>
            </div>

            <FlaggedFeature flag={FEATURE_FLAGS.AI_SESSION_SUMMARY} match={true}>
                {summariseFn && (
                    <>
                        <LemonDivider className="" />
                        <div className="gap-1 pt-1 pb-2 px-1.5">
                            {recording.summary ? (
                                <span>{recording.summary}</span>
                            ) : (
                                <div>
                                    <LemonButton
                                        size="small"
                                        type="primary"
                                        icon={<IconMagicWand />}
                                        onClick={(e) => {
                                            e.preventDefault()
                                            e.stopPropagation()
                                            if (!recording.summary) {
                                                summariseFn(recording)
                                            }
                                        }}
                                        loading={sessionSummaryLoading}
                                    >
                                        Generate AI summary
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </>
                )}
            </FlaggedFeature>
        </div>
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
