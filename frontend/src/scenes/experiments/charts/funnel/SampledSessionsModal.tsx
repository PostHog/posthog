import { useEffect, useState } from 'react'
import { LemonButton, LemonModal, LemonTable, LemonTabs } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import { NodeKind } from '~/queries/schema/schema-general'

interface SessionData {
    sessionId: string
    eventUuid: string
    hasRecording?: boolean
}

interface SampledSessionsModalProps {
    isOpen: boolean
    onClose: () => void
    stepsEventData: Array<Array<[string, string]>> // From experiment response
    stepNames: string[] // Names of funnel steps
    variant: string
}

export function SampledSessionsModal({
    isOpen,
    onClose,
    stepsEventData,
    stepNames,
    variant,
}: SampledSessionsModalProps): JSX.Element {
    const [recordingAvailability, setRecordingAvailability] = useState<Map<string, boolean>>(new Map())
    const [loading, setLoading] = useState(false)
    const [activeTab, setActiveTab] = useState('0')

    // Parse sessions from steps data
    const parseSessionsByStep = (): Map<number, SessionData[]> => {
        const sessionsByStep = new Map<number, SessionData[]>()

        stepsEventData.forEach((stepData, stepIndex) => {
            const sessions: SessionData[] = stepData.map(([sessionId, eventUuid]) => ({
                sessionId,
                eventUuid,
            }))
            sessionsByStep.set(stepIndex, sessions)
        })

        return sessionsByStep
    }

    const sessionsByStep = parseSessionsByStep()

    // Get all unique session IDs
    const allSessionIds = Array.from(
        new Set(
            Array.from(sessionsByStep.values())
                .flat()
                .map((s) => s.sessionId)
        )
    )

    // Create a stable string key for the dependency array
    const sessionIdsKey = allSessionIds.join(',')

    // Check recording availability for all sessions
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
                    limit: allSessionIds.length,
                })

                const availabilityMap = new Map<string, boolean>()
                response.results?.forEach((recording) => {
                    availabilityMap.set(recording.id, true)
                })

                setRecordingAvailability(availabilityMap)
            } catch (error) {
                console.error('Failed to check recording availability:', error)
            } finally {
                setLoading(false)
            }
        }

        void checkRecordingAvailability()
    }, [isOpen, sessionIdsKey, allSessionIds.length, allSessionIds])

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
            title: 'Session ID',
            key: 'sessionId',
            render: (_, session) => (
                <span className="font-mono text-xs" title={session.sessionId}>
                    {session.sessionId.slice(0, 8)}...
                </span>
            ),
            width: '40%',
        },
        {
            title: 'Recording',
            key: 'recording',
            render: (_, session) => {
                const hasRecording = recordingAvailability.get(session.sessionId) || false

                if (loading) {
                    return <Spinner className="text-sm" />
                }

                if (hasRecording) {
                    return (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPlayCircle />}
                            onClick={() => openSessionRecording(session.sessionId, session.eventUuid)}
                        >
                            View recording
                        </LemonButton>
                    )
                }

                return <span className="text-muted text-xs">No recording available</span>
            },
            width: '60%',
        },
    ]

    // Create tabs for each step
    const tabs = stepNames.map((stepName, index) => {
        const sessions = sessionsByStep.get(index) || []
        const recordingsCount = sessions.filter(s => recordingAvailability.get(s.sessionId)).length

        return {
            key: String(index),
            label: (
                <div className="flex flex-col items-start">
                    <div className="font-semibold">{stepName || `Step ${index + 1}`}</div>
                    <div className="text-xs text-muted">
                        {sessions.length} session{sessions.length !== 1 ? 's' : ''}
                        {!loading && recordingsCount > 0 && ` (${recordingsCount} with recording${recordingsCount !== 1 ? 's' : ''})`}
                    </div>
                </div>
            ),
            content: (
                <div className="mt-2">
                    {sessions.length > 0 ? (
                        <LemonTable
                            columns={columns}
                            dataSource={sessions}
                            size="small"
                            emptyState="No sessions sampled for this step"
                            loading={loading}
                        />
                    ) : (
                        <div className="text-muted text-center py-8">
                            No users reached this step
                        </div>
                    )}
                </div>
            ),
        }
    })

    // Add a special tab for users who didn't enter the funnel (step -1)
    if (stepsEventData.length > stepNames.length) {
        const droppedOffSessions = sessionsByStep.get(stepsEventData.length - 1) || []
        const droppedOffRecordingsCount = droppedOffSessions.filter(s => recordingAvailability.get(s.sessionId)).length

        tabs.unshift({
            key: 'dropped',
            label: (
                <div className="flex flex-col items-start">
                    <div className="font-semibold">Didn't enter funnel</div>
                    <div className="text-xs text-muted">
                        {droppedOffSessions.length} session{droppedOffSessions.length !== 1 ? 's' : ''}
                        {!loading && droppedOffRecordingsCount > 0 && ` (${droppedOffRecordingsCount} with recording${droppedOffRecordingsCount !== 1 ? 's' : ''})`}
                    </div>
                </div>
            ),
            content: (
                <div className="mt-2">
                    {droppedOffSessions.length > 0 ? (
                        <LemonTable
                            columns={columns}
                            dataSource={droppedOffSessions}
                            size="small"
                            emptyState="No sessions sampled"
                            loading={loading}
                        />
                    ) : (
                        <div className="text-muted text-center py-8">
                            No sessions sampled for users who didn't enter the funnel
                        </div>
                    )}
                </div>
            ),
        })
    }

    const totalRecordingsAvailable = Array.from(recordingAvailability.values()).filter(Boolean).length

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={`Sampled Sessions - ${variant}`}
            width={720}
        >
            <div className="space-y-4">
                {/* Summary */}
                <div className="bg-bg-3000 rounded p-3 text-sm">
                    <div className="flex justify-between items-center">
                        <div>
                            <strong>{allSessionIds.length}</strong> unique session{allSessionIds.length !== 1 ? 's' : ''} sampled
                        </div>
                        {!loading && totalRecordingsAvailable > 0 && (
                            <div className="text-muted">
                                <strong>{totalRecordingsAvailable}</strong> with recording{totalRecordingsAvailable !== 1 ? 's' : ''} available
                            </div>
                        )}
                    </div>
                </div>

                {/* Tabs for each funnel step */}
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    tabs={tabs}
                />

                {/* Note about sampling */}
                <div className="text-xs text-muted border-t pt-2">
                    <strong>Note:</strong> This shows a sample of up to 100 sessions per step. Session recordings are only available for sessions that have been captured and not deleted.
                </div>
            </div>
        </LemonModal>
    )
}