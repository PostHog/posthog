import { PersonDisplay, TZLabel } from '@posthog/apps-common'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { NotFound } from 'lib/components/NotFound'
import { Playlist } from 'lib/components/Playlist/Playlist'
import { dayjs } from 'lib/dayjs'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { PropertyIcons } from 'scenes/session-recordings/playlist/SessionRecordingPreview'

import { ErrorTrackingGroupEvent, errorTrackingGroupSceneLogic } from '../errorTrackingGroupSceneLogic'

export const OverviewTab = (): JSX.Element => {
    const { group, events, groupLoading } = useValues(errorTrackingGroupSceneLogic)

    return groupLoading ? (
        <Spinner className="self-align-center justify-self-center" />
    ) : group ? (
        <div className="ErrorTracking__group">
            <div className="h-full space-y-2">
                <Playlist
                    title="Exceptions"
                    sections={[
                        {
                            key: 'exceptions',
                            title: 'Exceptions',
                            items: events.map((e) => ({ ...e, id: e.uuid })),
                            render: ListItemException,
                        },
                    ]}
                    listEmptyState={<div className="flex justify-center p-4">No exceptions found</div>}
                    content={({ activeItem: event }) =>
                        event ? (
                            <div className="h-full overflow-auto">
                                <div className="bg-bg-light p-1 flex justify-end border-b min-h-[42px]">
                                    <ViewSessionButton event={event} />
                                </div>
                                <div className="pl-2">
                                    <ErrorDisplay eventProperties={JSON.parse(event.properties)} />
                                </div>
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
    ) : (
        <NotFound object="exception" />
    )
}

const ViewSessionButton = ({ event }: { event: ErrorTrackingGroupEvent }): JSX.Element | null => {
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    const properties = JSON.parse(event.properties)

    return (
        <LemonButton
            size="small"
            onClick={() => {
                const fiveSecondsBeforeEvent = dayjs(event.timestamp).valueOf() - 5000
                openSessionPlayer({ id: properties.$session_id }, Math.max(fiveSecondsBeforeEvent, 0))
            }}
            disabledReason={
                !properties.$session_id ? 'There was no $session_id associated with this exception' : undefined
            }
        >
            View recording
        </LemonButton>
    )
}

const ListItemException = ({
    item: event,
    isActive,
}: {
    item: ErrorTrackingGroupEvent
    isActive: boolean
}): JSX.Element => {
    const properties = JSON.parse(event.properties)

    const recordingProperties = ['$browser', '$device_type', '$os']
        .flatMap((property) => {
            let value = properties[property]
            const label = value
            if (property === '$device_type') {
                value = properties['$device_type'] || properties['$initial_device_type']
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
                <PropertyIcons recordingProperties={recordingProperties} iconClassNames="text-muted" />
            </div>
            {properties.$current_url && <div className="text-xs text-muted truncate">{properties.$current_url}</div>}
            <TZLabel
                className="overflow-hidden text-ellipsis text-xs text-muted shrink-0"
                time={event.timestamp}
                placement="right"
                showPopover={false}
            />
        </div>
    )
}
