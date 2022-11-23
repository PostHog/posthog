import { SessionRecordingType } from '~/types'
import { colonDelimitedDuration } from 'lib/utils'
import clsx from 'clsx'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { IconSchedule } from 'lib/components/icons'
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

    return (
        <li
            key={recording.id}
            className={clsx(
                'SessionRecordingsPlaylist__list-item',
                'flex flex-row py-2 pr-4 pl-0 cursor-pointer relative overflow-hidden',
                isActive && 'bg-primary-highlight font-semibold'
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
            <div className="grow">
                <div className="flex items-center justify-between">
                    <div className="truncate font-medium text-primary ph-no-capture">
                        {asDisplay(recording.person, 25)}
                    </div>

                    <div className="flex-1" />

                    {propertyIcons}
                </div>

                <div className="flex items-center justify-between">
                    <TZLabel
                        className="overflow-hidden text-ellipsis"
                        time={recording.start_time}
                        formatDate="MMMM DD, YYYY"
                        formatTime="h:mm A"
                    />
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
            </div>
        </li>
    )
}
