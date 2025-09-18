import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonTable, LemonTabs, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'

interface SampledSessionsModalProps {
    isOpen: boolean
    onClose: () => void
    stepsEventData: Array<[string, string]>
    prevStepsEventData: Array<[string, string]>
    stepName: string
    variant: string
}

export function SampledSessionsModal({
    isOpen,
    onClose,
    stepsEventData,
    prevStepsEventData,
    stepName,
    variant,
}: SampledSessionsModalProps): JSX.Element {
    const [recordingAvailability, setRecordingAvailability] = useState<
        Map<string, { hasRecording: boolean; distinct_id?: string }>
    >(new Map())
    const [loading, setLoading] = useState(false)
    const [activeTab, setActiveTab] = useState(stepName)

    // Get all unique session IDs - memoized to prevent recreating on each render
    const allSessionIds = useMemo(() => {
        return Array.from(new Set(stepsEventData.concat(prevStepsEventData).map((s) => s[0])))
    }, [stepsEventData, prevStepsEventData])

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

    const columns: LemonTableColumns<[string, string]> = [
        {
            title: 'Session ID',
            key: 'sessionId',
            render: (_, sutuple) => {
                const sessionInfo = recordingAvailability.get(sutuple[0])
                const distinct_id = sessionInfo?.distinct_id

                if (distinct_id) {
                    return (
                        <Link
                            to={urls.personByDistinctId(distinct_id)}
                            subtle
                            className="font-mono text-xs"
                            title={sutuple[0]}
                        >
                            {sutuple[0]}
                        </Link>
                    )
                }

                return (
                    <span className="font-mono text-xs" title={sutuple[0]}>
                        {sutuple[0]}
                    </span>
                )
            },
            width: '40%',
        },
        {
            title: 'Recording',
            key: 'recording',
            render: (_, sutuple) => {
                const sessionInfo = recordingAvailability.get(sutuple[0])
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
                            onClick={() => openSessionRecording(sutuple[0], sutuple[1])}
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

    let tabs = [
        {
            key: stepName,
            label: (
                <div className="flex flex-col items-start">
                    <div className="font-semibold">{stepName}</div>
                    <div className="text-xs text-muted">{stepsEventData.length} sessions</div>
                </div>
            ),
            content: (
                <div className="mt-2">
                    <LemonTable
                        columns={columns}
                        dataSource={stepsEventData}
                        size="small"
                        emptyState="No sessions sampled for this step"
                        loading={loading}
                    />
                </div>
            ),
        },
    ]

    // Add a "Dropped off" tab that shows sessions from the previous step
    if (prevStepsEventData.length > 0) {
        tabs.push({
            key: 'dropped',
            label: (
                <div className="flex flex-col items-start">
                    <div className="font-semibold">Dropped off</div>
                    <div className="text-xs text-muted">{prevStepsEventData.length} sessions</div>
                </div>
            ),
            content: (
                <div className="mt-2">
                    <LemonTable
                        columns={columns}
                        dataSource={prevStepsEventData}
                        size="small"
                        emptyState="No sessions sampled"
                        loading={loading}
                    />
                </div>
            ),
        })
    }

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title={`Sampled Sessions - ${variant}`} width={720}>
            <div className="space-y-4">
                <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} />

                <div className="text-xs text-muted border-t pt-2">
                    <strong>Note:</strong> This shows a sample of up to 100 sessions per step. Session recordings are
                    only available for sessions that have been captured and not deleted.
                </div>
            </div>
        </LemonModal>
    )
}
