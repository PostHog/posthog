import { SessionRecordingType } from '~/types'
import { colonDelimitedDuration } from 'lib/utils'
import clsx from 'clsx'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { IconAutocapture, IconKeyboard, IconPinFilled, IconSchedule } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { RecordingDebugInfo } from '../debug/RecordingDebugInfo'

export interface SessionRecordingPlaylistItemProps {
    recording: SessionRecordingType
    recordingProperties?: Record<string, any> // Loaded and rendered later
    recordingPropertiesLoading: boolean
    isActive: boolean
    onClick: () => void
    onPropertyClick: (property: string, value?: string) => void
}

export function SessionRecordingPlaylistItem({
    recording,
    isActive,
    onClick,
    onPropertyClick,
    recordingProperties,
    recordingPropertiesLoading,
}: SessionRecordingPlaylistItemProps): JSX.Element {
    const formattedDuration = colonDelimitedDuration(recording.recording_duration)
    const durationParts = formattedDuration.split(':')

    const iconClassnames = clsx(
        'SessionRecordingsPlaylist__list-item__property-icon text-base text-muted-alt',
        !isActive && 'opacity-75'
    )
    const iconPropertyKeys = ['$browser', '$device_type', '$os', '$geoip_country_code']
    const iconProperties =
        recordingProperties && Object.keys(recordingProperties).length > 0
            ? recordingProperties
            : recording.person?.properties || {}

    const propertyIcons = (
        <div className="flex flex-row flex-nowrap shrink-0 gap-1 h-6 ph-no-capture">
            {!recordingPropertiesLoading ? (
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
                            onClick={onPropertyClick}
                            className={iconClassnames}
                            property={property}
                            value={value}
                            tooltipTitle={() => (
                                <div className="text-center">
                                    Click to filter for
                                    <br />
                                    <span className="font-medium">{tooltipValue ?? 'N/A'}</span>
                                </div>
                            )}
                        />
                    )
                })
            ) : (
                <LemonSkeleton className="w-18 my-1" />
            )}
        </div>
    )

    const firstPath = recording.start_url?.replace(/https?:\/\//g, '').split(/[?|#]/)[0]

    // TODO: Modify onClick to only react to shift+click

    return (
        <li
            key={recording.id}
            className={clsx(
                'SessionRecordingsPlaylist__list-item',
                'flex flex-row py-2 pr-4 pl-0 cursor-pointer relative overflow-hidden',
                isActive && 'bg-primary-highlight'
            )}
            onClick={() => onClick()}
        >
            <div className="w-2 h-2 mx-2">
                {!recording.viewed ? (
                    <Tooltip title={'Indicates the recording has not been watched yet'}>
                        <div
                            className="w-2 h-2 mt-2 rounded-full bg-primary-light"
                            aria-label="unwatched-recording-label"
                        />
                    </Tooltip>
                ) : null}
            </div>
            <div className="grow overflow-hidden space-y-px">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1 shrink">
                        {(recording.pinned_count ?? 0) > 0 && (
                            <Tooltip
                                placement="topRight"
                                title={`This recording is pinned on ${recording.pinned_count} playlists`}
                            >
                                <IconPinFilled className="text-sm text-orange" />
                            </Tooltip>
                        )}
                        <div className="truncate font-medium text-primary ph-no-capture">
                            {asDisplay(recording.person)}
                        </div>
                    </div>
                    <div className="flex-1" />
                    <div className="flex items-center flex-1 justify-end font-semibold">
                        <IconSchedule className={iconClassnames} />
                        <span>
                            <span className={clsx(durationParts[0] === '00' && 'opacity-50 font-normal')}>
                                {durationParts[0]}:
                            </span>
                            <span
                                className={clsx({
                                    'opacity-50 font-normal': durationParts[0] === '00' && durationParts[1] === '00',
                                })}
                            >
                                {durationParts[1]}:
                            </span>
                            {durationParts[2]}
                        </span>
                    </div>
                </div>

                <div className="flex items-center justify-between gap-2">
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
                    <TZLabel className="overflow-hidden text-ellipsis text-xs" time={recording.start_time} />
                </div>

                <div className="flex items-center justify-between gap-4 w-2/3">
                    <span className="flex items-center gap-1 overflow-hidden text-muted text-xs">
                        <span title={`First URL: ${recording.start_url}`} className="truncate">
                            {firstPath}
                        </span>
                    </span>
                </div>
            </div>

            <RecordingDebugInfo recording={recording} className="absolute right-0 bottom-0 m-2" />
        </li>
    )
}

export function SessionRecordingPlaylistItemSkeleton(): JSX.Element {
    return (
        <div className="p-4 space-y-2">
            <LemonSkeleton className="w-1/2" />
            <LemonSkeleton className="w-1/3" />
        </div>
    )
}
