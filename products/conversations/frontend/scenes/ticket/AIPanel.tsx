import { LemonCollapse, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import {
    type AITriage,
    aiTriageResultLabel,
    aiTriageResultTagType,
    aiTriageTicketTypeDescription,
    aiTriageTicketTypeLabel,
} from '../../types'

interface AIPanelProps {
    aiTriage?: AITriage
}

function AITriageHeaderTag({ aiTriage }: { aiTriage?: AITriage }): JSX.Element | null {
    if (!aiTriage?.status) {
        return null
    }
    if (aiTriage.status === 'in_progress') {
        return <Spinner className="text-sm ml-1" />
    }
    if (aiTriage.result) {
        return (
            <LemonTag type={aiTriageResultTagType(aiTriage.result)} size="small" className="ml-1">
                {aiTriageResultLabel[aiTriage.result]}
            </LemonTag>
        )
    }
    return null
}

export function AIPanel({ aiTriage }: AIPanelProps): JSX.Element {
    const hasData = aiTriage && aiTriage.status

    return (
        <LemonCollapse
            className="bg-surface-primary"
            panels={[
                {
                    key: 'ai_triage',
                    header: (
                        <span className="flex items-center">
                            AI triage
                            <AITriageHeaderTag aiTriage={aiTriage} />
                        </span>
                    ),
                    content: hasData ? (
                        <div className="space-y-2 text-xs">
                            {aiTriage.status && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Status</span>
                                    <span className="capitalize">
                                        {aiTriage.status === 'in_progress' ? 'In progress' : aiTriage.status}
                                    </span>
                                </div>
                            )}
                            {aiTriage.result && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Result</span>
                                    <LemonTag type={aiTriageResultTagType(aiTriage.result)} size="small">
                                        {aiTriageResultLabel[aiTriage.result]}
                                    </LemonTag>
                                </div>
                            )}
                            {aiTriage.ticket_type && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Ticket type</span>
                                    <Tooltip title={aiTriageTicketTypeDescription[aiTriage.ticket_type]}>
                                        <LemonTag size="small">
                                            {aiTriageTicketTypeLabel[aiTriage.ticket_type] ?? aiTriage.ticket_type}
                                        </LemonTag>
                                    </Tooltip>
                                </div>
                            )}
                            {aiTriage.confidence != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Confidence</span>
                                    <span>{(aiTriage.confidence * 100).toFixed(0)}%</span>
                                </div>
                            )}
                            {aiTriage.attempts != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Attempts</span>
                                    <span>{aiTriage.attempts}</span>
                                </div>
                            )}
                            {aiTriage.needs_diagnostics != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Needs diagnostics</span>
                                    <span>{aiTriage.needs_diagnostics ? 'Yes' : 'No'}</span>
                                </div>
                            )}
                            {aiTriage.diagnostics_allowed != null && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Diagnostics allowed</span>
                                    <span>{aiTriage.diagnostics_allowed ? 'Yes' : 'No'}</span>
                                </div>
                            )}
                            {aiTriage.started_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Started</span>
                                    <TZLabel time={aiTriage.started_at} />
                                </div>
                            )}
                            {aiTriage.finished_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-alt">Finished</span>
                                    <TZLabel time={aiTriage.finished_at} />
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-muted-alt text-xs">AI has not processed this ticket yet.</div>
                    ),
                },
            ]}
        />
    )
}
