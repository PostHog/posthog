import { PersonDisplay } from '@posthog/apps-common'
import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { NotFound } from 'lib/components/NotFound'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

import { ErrorTrackingFilters } from './ErrorTrackingFilters'
import { errorTrackingGroupSceneLogic, ExceptionEventType } from './errorTrackingGroupSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        id,
    }),
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { events, eventsLoading } = useValues(errorTrackingGroupSceneLogic)
    const [activeTab, setActiveTab] = useState<'details' | 'recordings'>('details')

    return eventsLoading ? (
        <Spinner className="self-align-center justify-self-center" />
    ) : events && events.length > 0 ? (
        <div>
            <ErrorTrackingFilters showOrder={false} />
            <LemonTabs
                tabs={[
                    {
                        key: 'details',
                        label: 'Details',
                        content: <ExceptionDetails events={events} />,
                    },
                    {
                        key: 'recordings',
                        label: 'Recordings',
                        content: (
                            <ExceptionRecordings
                                sessionIds={events.map((e) => e.properties.$session_id).filter(Boolean)}
                            />
                        ),
                    },
                ]}
                activeKey={activeTab}
                onChange={setActiveTab}
            />
        </div>
    ) : (
        <NotFound object="exception" />
    )
}

const ExceptionDetails = ({ events }: { events: ExceptionEventType[] }): JSX.Element => {
    const [activeEventId, setActiveEventId] = useState<number>(events.length - 1)

    const event = events[activeEventId]

    return (
        <div className="space-y-4">
            {events.length > 1 && (
                <div className="flex space-x-1 items-center">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconChevronLeft />}
                        onClick={() => setActiveEventId(activeEventId - 1)}
                        disabledReason={activeEventId <= 0 && 'No earlier examples'}
                    />
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconChevronRight />}
                        onClick={() => setActiveEventId(activeEventId + 1)}
                        disabledReason={activeEventId >= events.length - 1 && 'No newer examples'}
                    />
                    <span>
                        {activeEventId + 1} of {events.length}
                    </span>
                </div>
            )}
            <div className="bg-bg-light border rounded p-2">
                <PersonDisplay person={event.person} withIcon />
            </div>
            <ErrorDisplay eventProperties={event.properties} />
        </div>
    )
}

const ExceptionRecordings = ({ sessionIds }: { sessionIds: string[] }): JSX.Element => {
    return (
        <div className="SessionRecordingPlaylistHeightWrapper">
            <SessionRecordingsPlaylist pinnedRecordings={sessionIds} />
        </div>
    )
}
