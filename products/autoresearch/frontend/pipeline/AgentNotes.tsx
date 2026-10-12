import { useValues } from 'kea'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'

/** What the newest completed run learned, and what the agent plans to try next. Renders nothing before any notes exist. */
export function AgentNotes(): JSX.Element | null {
    const { agentNotes } = useValues(autoresearchPipelineLogic)
    if (!agentNotes) {
        return null
    }
    return (
        <div className="border rounded p-3 space-y-2">
            <div className="text-sm font-semibold">Agent notes</div>
            {agentNotes.distillation && <div className="text-sm">{agentNotes.distillation}</div>}
            {agentNotes.recommendedNext && (
                <div className="text-sm text-muted">Next it plans to: {agentNotes.recommendedNext}</div>
            )}
            <div className="text-xs text-muted">From run {agentNotes.runNumber}</div>
        </div>
    )
}
