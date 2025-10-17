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

const getEventsUrl = (key: string, value: string): string => {
    const eventsQuery = getDefaultEventsSceneQuery([
        {
            type: PropertyFilterType.EventMetadata,
            key: key,
            value: [value],
            operator: PropertyOperator.Exact,
        },
    ])
    // Override the default time range to 90 days
    if ('after' in eventsQuery.source) {
        eventsQuery.source.after = '-90d'
    }
    return combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: eventsQuery }).url
}

const getLinkTextAndUrl = (session: SessionData): { text: string; url: string } => {
    if (session.session_id) {
        return {
            text: session.session_id,
            url: getEventsUrl('$session_id', session.session_id),
        }
    } else if (session.person_id) {
        return {
            text: session.person_id,
            url: getEventsUrl('person_id', session.person_id),
        }
    }
    return {
        text: session.event_uuid,
        url: getEventsUrl('uuid', session.event_uuid),
    }
}

export function SampledSessionsModal(): JSX.Element {
    const { isOpen, modalData, recordingAvailability, recordingAvailabilityLoading } =
        useValues(sampledSessionsModalLogic)
    const { closeModal } = useActions(sampledSessionsModalLogic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    if (!modalData) {
        return <></>
    }

    const { sessionData, stepName, variant } = modalData

    const openSessionRecording = (sessionId: string, eventUuid: string): void => {
        openSessionPlayer({
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
            title: 'Person',
            key: 'personId',
            render: (_, session) => {
                const { text, url } = getLinkTextAndUrl(session)
                return (
                    <div className="flex items-center gap-1">
                        <Link
                            to={url}
                            onClick={(e) => {
                                e.preventDefault()
                                sceneLogic.actions.newTab(url)
                            }}
                            className="font-mono text-xs whitespace-nowrap"
                            title={`View events for ${text}`}
                        >
                            {text}
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
        <LemonModal isOpen={isOpen} onClose={closeModal} title={`Sampled persons - ${variant}`} width={720}>
            <div className="space-y-4">
                <div className="text">
                    Persons in <strong>{variant}</strong> with <strong>{stepName}</strong> as their last funnel step.
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
                    <strong>Note:</strong> This shows a sample of up to 100 persons per step. Session recordings are
                    only available for sessions that have been captured and not deleted.
                </div>
            </div>
        </LemonModal>
    )
}
