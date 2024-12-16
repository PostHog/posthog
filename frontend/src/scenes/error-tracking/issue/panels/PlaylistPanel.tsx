import { PersonDisplay, TZLabel } from '@posthog/apps-common'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Playlist } from 'lib/components/Playlist/Playlist'
import { ErrorTrackingEvent, errorTrackingIssueSceneLogic } from 'scenes/error-tracking/errorTrackingIssueSceneLogic'
import { PropertyIcons } from 'scenes/session-recordings/playlist/SessionRecordingPreview'

export const PlaylistPanel = (): JSX.Element => {
    const { events, issueLoading, eventsLoading, activeEventUUID } = useValues(errorTrackingIssueSceneLogic)
    const { loadEvents, setActiveEventUUID } = useActions(errorTrackingIssueSceneLogic)

    return (
        <Playlist
            embedded
            showHeader={false}
            loading={issueLoading || eventsLoading}
            sections={[
                {
                    key: 'exceptions',
                    title: 'Exceptions',
                    items: events.map((e) => ({ ...e, id: e.uuid })),
                    render: ListItemException,
                },
            ]}
            onSelect={({ uuid }) => setActiveEventUUID(uuid)}
            activeItemId={activeEventUUID}
            listEmptyState={<div className="flex justify-center p-4">No exceptions found</div>}
            onScrollListEdge={(edge) => {
                if (edge === 'bottom' && !eventsLoading) {
                    loadEvents()
                }
            }}
        />
    )
}

const ListItemException = ({
    item: { timestamp, properties, person },
    isActive,
}: {
    item: ErrorTrackingEvent
    isActive: boolean
}): JSX.Element => {
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
        <div
            className={clsx(
                'cursor-pointer p-2 space-y-1 border-l-4',
                isActive ? 'border-primary-3000' : 'border-transparent'
            )}
        >
            <div className="line-clamp-1">
                <PersonDisplay person={person} withIcon noPopover noLink />
            </div>
            <div className="flex justify-between items-center space-x-3">
                <TZLabel
                    className="overflow-hidden text-ellipsis text-xs text-muted shrink-0"
                    time={timestamp}
                    placement="right"
                    showPopover={false}
                />
                <PropertyIcons recordingProperties={recordingProperties} iconClassNames="text-muted" />
            </div>
        </div>
    )
}
