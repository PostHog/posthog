import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { LemonButton, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconOpenInNew, IconPlayCircle } from 'lib/lemon-ui/icons'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { sceneLogic } from 'scenes/sceneLogic'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { SessionData } from '~/queries/schema/schema-general'
import { ActivityTab, PropertyFilterType, PropertyOperator } from '~/types'

import { sampledSessionsModalLogic } from './sampledSessionsModalLogic'

export function SampledSessionsModal(): JSX.Element {
    const { isOpen, modalData, recordingAvailability, recordingAvailabilityLoading } =
        useValues(sampledSessionsModalLogic)
    const { closeModal } = useActions(sampledSessionsModalLogic)

    if (!modalData) {
        return <></>
    }

    const { sessionData, stepName, variant } = modalData

    // Helper function to get events URL for a session ID
    const getEventsUrlForSession = (sessionId: string): string => {
        const eventsQuery = getDefaultEventsSceneQuery([
            {
                type: PropertyFilterType.EventMetadata,
                key: '$session_id',
                value: [sessionId],
                operator: PropertyOperator.Exact,
            },
        ])
        // Override the default time range to 90 days
        if ('after' in eventsQuery.source) {
            eventsQuery.source.after = '-90d'
        }
        return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: eventsQuery }).url
    }

    const openSessionRecording = (sessionId: string, eventUuid: string): void => {
        sessionPlayerModalLogic.actions.openSessionPlayer({
            id: sessionId,
            matching_events: [
                {
                    session_id: sessionId,
                    events: [{ uuid: eventUuid }],
                },
            ],
        })
    }

    const columns: LemonTableColumns<SessionData> = [
        {
            title: 'Session',
            key: 'sessionId',
            render: (_, session) => {
                const eventsUrl = getEventsUrlForSession(session.session_id)
                return (
                    <div className="flex items-center gap-1">
                        <Link
                            to={eventsUrl}
                            onClick={(e) => {
                                e.preventDefault()
                                sceneLogic.actions.newTab(eventsUrl)
                            }}
                            className="font-mono text-xs whitespace-nowrap"
                            title={`View events for session ${session.session_id}`}
                        >
                            {session.session_id}
                            <IconOpenInNew style={{ fontSize: 14 }} />
                        </Link>
                    </div>
                )
            },
            width: '40%',
        },
        {
            title: 'Recording',
            key: 'recording',
            render: (_, session) => {
                const sessionInfo = recordingAvailability.get(session.session_id)
                const hasRecording = sessionInfo?.hasRecording || false

                if (recordingAvailabilityLoading) {
                    return <Spinner className="text-sm" />
                }

                if (hasRecording) {
                    return (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPlayCircle />}
                            onClick={() => openSessionRecording(session.session_id, session.event_uuid)}
                        >
                            View recording
                        </LemonButton>
                    )
                }
            },
            width: '60%',
        },
    ]

    return (
        <LemonModal isOpen={isOpen} onClose={closeModal} title={`Sampled sessions - ${variant}`} width={720}>
            <div className="space-y-4">
                <div className="text">
                    Users in <strong>{variant}</strong> with <strong>{stepName}</strong> as their last funnel step.
                </div>
                <div className="mt-2">
                    <LemonTable
                        columns={columns}
                        dataSource={sessionData}
                        size="small"
                        emptyState="No sessions for this step"
                        loading={recordingAvailabilityLoading}
                    />
                </div>

                <div className="text-xs text-muted border-t pt-2">
                    <strong>Note:</strong> This shows a sample of up to 100 sessions per step. Session recordings are
                    only available for sessions that have been captured and not deleted.
                </div>
            </div>
        </LemonModal>
    )
}
