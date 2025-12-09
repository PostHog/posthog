import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { SessionData } from '~/queries/schema/schema-general'
import { PersonsTabType } from '~/types'

import { sampledSessionsModalLogic } from './sampledSessionsModalLogic'

export function SampledSessionsModal(): JSX.Element {
    const { isOpen, modalData, recordingAvailability, recordingAvailabilityLoading } =
        useValues(sampledSessionsModalLogic)
    const { closeModal } = useActions(sampledSessionsModalLogic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    if (!modalData) {
        return <></>
    }

    const { sessionData, stepName, variant } = modalData

    const openSessionRecording = (session: SessionData): void => {
        openSessionPlayer({
            id: session.session_id,
            matching_events: [
                {
                    session_id: session.session_id,
                    events: [{ uuid: session.event_uuid, timestamp: session.timestamp }],
                },
            ],
        })
    }

    const columns: LemonTableColumns<SessionData> = [
        {
            title: 'Person',
            key: 'personId',
            render: (_, session) => (
                <PersonDisplay
                    person={{ id: session.person_id }}
                    displayName={session.person_id}
                    withIcon={true}
                    href={urls.personByUUID(session.person_id, true, PersonsTabType.EVENTS)}
                />
            ),
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
                            onClick={() => openSessionRecording(session)}
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
