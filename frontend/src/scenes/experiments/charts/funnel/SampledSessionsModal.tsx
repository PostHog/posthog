import { LemonButton, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

export interface SampledSession {
    session_id: string
    person_id?: string
}

interface SampledSessionsModalProps {
    isOpen: boolean
    onClose: () => void
    title: string
    sessions: SampledSession[]
    variant: string
    stepName: string
    converted: boolean
}

export function SampledSessionsModal({
    isOpen,
    onClose,
    title,
    sessions,
    variant,
    stepName,
    converted,
}: SampledSessionsModalProps): JSX.Element {
    const columns: LemonTableColumns<SampledSession> = [
        {
            title: 'Session',
            render: (_, session) => <span className="font-mono text-xs">{session.session_id.slice(0, 8)}...</span>,
        },
        {
            title: 'Recording',
            render: (_, session) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlayCircle />}
                    onClick={() => {
                        sessionPlayerModalLogic.actions.openSessionPlayer({ id: session.session_id })
                    }}
                >
                    View recording
                </LemonButton>
            ),
        },
    ]

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title={`${title} - Sampled Recordings`} width={600}>
            <div className="space-y-4">
                <div className="text-muted">
                    Showing sampled recordings for variant "{variant}" at step "{stepName}"
                    {converted ? ' (converted)' : ' (dropped off)'}
                </div>
                <LemonTable columns={columns} dataSource={sessions} emptyState="No sampled recordings available" />
                <div className="text-xs text-muted">
                    Note: This shows a sample of up to 10 recordings, not all users.
                </div>
            </div>
        </LemonModal>
    )
}
