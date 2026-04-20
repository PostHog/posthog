import { useActions, useValues } from 'kea'

import { LemonModal, LemonTable } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs, dayjs, dayjsLocalToTimezone } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { teamLogic } from 'scenes/teamLogic'

import { SessionData } from '~/queries/schema/schema-general'

import { sampledSessionsModalLogic } from './sampledSessionsModalLogic'

/** Bare datetime strings (no Z or offset) are assumed to be in the project timezone. */
export const parseTimestamp = (timestamp: string, timezone: string): Dayjs => {
    if (/([Zz]|[+-]\d{2}:?\d{2})\s*$/.test(timestamp)) {
        return dayjs(timestamp)
    }
    return dayjsLocalToTimezone(timestamp, timezone)
}

export function SampledSessionsModal(): JSX.Element {
    const {
        isOpen,
        modalData,
        recordingAvailability,
        recordingAvailabilityLoading,
        personDetails,
        personDetailsLoading,
    } = useValues(sampledSessionsModalLogic)
    const { closeModal } = useActions(sampledSessionsModalLogic)
    const { timezone } = useValues(teamLogic)

    if (!modalData) {
        return <></>
    }

    const { sessionData, stepName, variant } = modalData

    const columns: LemonTableColumns<SessionData> = [
        {
            title: 'Person',
            key: 'personId',
            render: (_, session) => {
                const person = personDetails.get(session.person_id)
                if (person) {
                    return <PersonDisplay person={person} withIcon />
                }
                if (personDetailsLoading) {
                    return <span className="text-muted text-xs">Loading…</span>
                }
                return <span className="font-mono text-xs">{session.person_id}</span>
            },
            width: '40%',
        },
        {
            title: 'Recording',
            key: 'recording',
            render: (_, session) => {
                const sessionInfo = recordingAvailability.get(session.session_id)
                const hasRecording = sessionInfo?.hasRecording || false

                return (
                    <ViewRecordingButton
                        sessionId={session.session_id}
                        timestamp={parseTimestamp(session.timestamp, timezone)}
                        matchingEvents={[
                            {
                                session_id: session.session_id,
                                events: [{ uuid: session.event_uuid, timestamp: session.timestamp }],
                            },
                        ]}
                        size="xsmall"
                        type="secondary"
                        openPlayerIn={RecordingPlayerType.Modal}
                        loading={recordingAvailabilityLoading}
                        hasRecording={hasRecording}
                    />
                )
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
