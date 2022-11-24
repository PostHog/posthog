import { SessionRecordingType } from '~/types'
import { colonDelimitedDuration } from 'lib/utils'
import clsx from 'clsx'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { IconAutocapture, IconKeyboard, IconSchedule } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'

interface SessionRecordingPlaylistItemProps {
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
                    const value =
                        property === '$device_type'
                            ? iconProperties?.['$device_type'] || iconProperties?.['$initial_device_type']
                            : iconProperties?.[property]
                    return (
                        <PropertyIcon
                            key={property}
                            onClick={onPropertyClick}
                            className={iconClassnames}
                            property={property}
                            value={value}
                            tooltipTitle={(_, value) => (
                                <div className="text-center">
                                    Click to filter for
                                    <br />
                                    <span className="font-medium">{value ?? 'N/A'}</span>
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

    const firstPath = recording.urls?.[0].replace(/https?:\/\//g, '').split(/[?|#]/)[0]

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
                    <div className="truncate font-medium text-primary ph-no-capture">{asDisplay(recording.person)}</div>

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
                        <span title={`First URL: ${recording.urls?.[0]}`} className="truncate">
                            {firstPath}
                        </span>
                    </span>
                </div>
            </div>
        </li>
    )
}
