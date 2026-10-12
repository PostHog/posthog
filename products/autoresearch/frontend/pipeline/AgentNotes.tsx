import { useValues } from 'kea'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { SectionCard } from './SectionCard'

/** What the newest completed run learned, and what the agent plans to try next. Renders nothing before any notes exist. */
export function AgentNotes(): JSX.Element | null {
    const { agentNotes } = useValues(autoresearchPipelineLogic)
    if (!agentNotes) {
        return null
    }
    return (
        <SectionCard title="Agent notes">
            {agentNotes.distillation && <div className="text-sm">{agentNotes.distillation}</div>}
            {agentNotes.recommendedNext && (
                <div className="text-sm text-muted">Next it plans to: {agentNotes.recommendedNext}</div>
            )}
            <div className="text-xs text-muted">From run {agentNotes.runNumber}</div>
        </SectionCard>
    )
}
