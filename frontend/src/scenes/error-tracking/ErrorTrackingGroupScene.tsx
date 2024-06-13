import { LemonButton, LemonTabs, Spinner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { NotFound } from 'lib/components/NotFound'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'

import { EventType } from '~/types'

import { errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingGroupScene,
    logic: errorTrackingGroupSceneLogic,
    paramsToProps: ({ params: { id } }): (typeof errorTrackingGroupSceneLogic)['props'] => ({
        id,
    }),
}

export function ErrorTrackingGroupScene(): JSX.Element {
    const { eventProperties, eventPropertiesLoading } = useValues(errorTrackingGroupSceneLogic)
    const [activeTab, setActiveTab] = useState<'details' | 'recordings'>('details')

    return eventPropertiesLoading ? (
        <Spinner />
    ) : eventProperties && eventProperties.length > 0 ? (
        <LemonTabs
            tabs={[
                {
                    key: 'details',
                    label: 'Details',
                    content: <ExceptionDetails eventProperties={eventProperties} />,
                },
                {
                    key: 'recordings',
                    label: 'Recordings',
                    content: (
                        <ExceptionRecordings sessionIds={eventProperties.map((p) => p.$session_id).filter(Boolean)} />
                    ),
                },
            ]}
            activeKey={activeTab}
            onChange={setActiveTab}
        />
    ) : (
        <NotFound object="exception" />
    )
}

const ExceptionDetails = ({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element => {
    const [activeEventId, setActiveEventId] = useState<number>(eventProperties.length - 1)

    return (
        <div>
            {eventProperties.length > 1 && (
                <div className="flex justify-end space-x-1">
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconChevronLeft />}
                        onClick={() => setActiveEventId(activeEventId - 1)}
                        disabledReason={activeEventId <= 0 && 'No earlier examples'}
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconChevronRight />}
                        onClick={() => setActiveEventId(activeEventId + 1)}
                        disabledReason={activeEventId >= eventProperties.length - 1 && 'No newer examples'}
                    />
                </div>
            )}
            <ErrorDisplay eventProperties={eventProperties[activeEventId]} />
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
