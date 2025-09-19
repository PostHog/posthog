import { combineUrl } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'
import { sceneLogic } from 'scenes/sceneLogic'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { NodeKind, SessionData } from '~/queries/schema/schema-general'
import { ActivityTab, PropertyFilterType, PropertyOperator } from '~/types'

interface SampledSessionsModalProps {
    isOpen: boolean
    onClose: () => void
    sessionData: SessionData[]
    stepName: string
    variant: string
}

export function SampledSessionsModal({
    isOpen,
    onClose,
    sessionData,
    stepName,
    variant,
}: SampledSessionsModalProps): JSX.Element {
    const [recordingAvailability, setRecordingAvailability] = useState<
        Map<string, { hasRecording: boolean; distinct_id?: string }>
    >(new Map())
    const [loading, setLoading] = useState(false)

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

    // Get all unique session IDs - memoized to prevent recreating on each render
    const allSessionIds = useMemo(() => {
        return Array.from(new Set(sessionData.map((s) => s.session_id)))
    }, [sessionData])

    // Check recording availability for sessions
    useEffect(() => {
        const checkRecordingAvailability = async (): Promise<void> => {
            if (!isOpen || allSessionIds.length === 0) {
                return
            }

            setLoading(true)
            try {
                const response = await api.recordings.list({
                    kind: NodeKind.RecordingsQuery,
                    session_ids: allSessionIds,
                    date_from: '-90d',
                    limit: allSessionIds.length,
                })

                const availabilityMap = new Map<string, { hasRecording: boolean; distinct_id?: string }>()
                response.results?.forEach((recording) => {
                    availabilityMap.set(recording.id, {
                        hasRecording: true,
                        distinct_id: recording.distinct_id,
                    })
                })
                // Also add entries for sessions without recordings
                allSessionIds.forEach((sessionId) => {
                    if (!availabilityMap.has(sessionId)) {
                        availabilityMap.set(sessionId, { hasRecording: false })
                    }
                })

                setRecordingAvailability(availabilityMap)
            } catch (error) {
                console.error('Failed to check recording availability:', error)
            } finally {
                setLoading(false)
            }
        }

        void checkRecordingAvailability()
    }, [isOpen, allSessionIds])

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
                    <Link
                        to={eventsUrl}
                        onClick={(e) => {
                            e.preventDefault()
                            sceneLogic.actions.newTab(eventsUrl)
                        }}
                        subtle
                        className="font-mono text-xs"
                        title={`View events for session ${session.session_id}`}
                    >
                        {session.session_id}
                    </Link>
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

                if (loading) {
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
        <LemonModal isOpen={isOpen} onClose={onClose} title={`Sampled Sessions - ${variant}`} width={720}>
            <div className="space-y-4">
                <div className="text">
                    Users in <strong>{variant}</strong> with <strong>{stepName}</strong> as their last funnel step.
                </div>
                <div className="mt-2">
                    <LemonTable
                        columns={columns}
                        dataSource={sessionData}
                        size="small"
                        emptyState="No sessions sampled for this step"
                        loading={loading}
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
