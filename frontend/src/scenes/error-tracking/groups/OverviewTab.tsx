import { PersonDisplay, TZLabel } from '@posthog/apps-common'
import { Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { Playlist } from 'lib/components/Playlist/Playlist'
import { PropertyIcons } from 'scenes/session-recordings/playlist/SessionRecordingPreview'

import { errorTrackingGroupSceneLogic, ExceptionEventType } from '../errorTrackingGroupSceneLogic'

export const OverviewTab = (): JSX.Element => {
    const { events, eventsLoading } = useValues(errorTrackingGroupSceneLogic)

    return eventsLoading ? (
        <Spinner className="self-align-center justify-self-center" />
    ) : (
        <div className="ErrorTracking__group">
            <div className="h-full space-y-2">
                <Playlist
                    title="Exceptions"
                    sections={[
                        {
                            key: 'exceptions',
                            title: 'Exceptions',
                            items: events,
                            render: ListItemException,
                        },
                    ]}
                    listEmptyState={<div className="flex justify-center p-4">No exceptions found</div>}
                    content={({ activeItem: event }) =>
                        event ? (
                            <div className="h-full overflow-auto pl-2">
                                <ErrorDisplay eventProperties={event.properties} />
                            </div>
                        ) : (
                            <EmptyMessage
                                title="No exception selected"
                                description="Please select an exception from the list on the left"
                            />
                        )
                    }
                    selectInitialItem
                />
            </div>
        </div>
    )
}

const ListItemException = ({ item: event, isActive }: { item: ExceptionEventType; isActive: boolean }): JSX.Element => {
    const properties = ['$browser', '$device_type', '$os']
        .flatMap((property) => {
            let value = event.properties[property]
            const label = value
            if (property === '$device_type') {
                value = event.properties['$device_type'] || event.properties['$initial_device_type']
            }

            return { property, value, label }
        })
        .filter((property) => !!property.value)

    return (
        <div className={clsx('cursor-pointer p-2 space-y-1', isActive && 'border-l-4 border-primary-3000')}>
            <div className="flex justify-between items-center space-x-3">
                <div className="line-clamp-1">
                    <PersonDisplay person={event.person} withIcon noPopover noLink />
                </div>
                <PropertyIcons recordingProperties={properties} iconClassNames="text-muted" />
            </div>
            {event.properties.$current_url && (
                <div className="text-xs text-muted truncate">{event.properties.$current_url}</div>
            )}
            <TZLabel
                className="overflow-hidden text-ellipsis text-xs text-muted shrink-0"
                time={event.timestamp}
                placement="right"
                showPopover={false}
            />
        </div>
    )
}
