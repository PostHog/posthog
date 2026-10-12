import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { SectionCard } from './SectionCard'

/** What the newest completed run learned, and what comes next. Renders nothing before any notes exist. */
export function AgentNotes(): JSX.Element | null {
    const { agentNotes } = useValues(autoresearchPipelineLogic)
    if (!agentNotes) {
        return null
    }
    const { readerSummary, nextSteps, distillation, recommendedNext, runNumber } = agentNotes
    // The agent writes its own notes for its next run, so they go behind a toggle when plainer notes exist.
    const hasReaderNotes = !!readerSummary || nextSteps.length > 0
    const hasWorkingNotes = !!distillation || !!recommendedNext
    return (
        <SectionCard title="What the agent learned">
            {hasReaderNotes ? (
                <>
                    {readerSummary && <div className="text-sm">{readerSummary}</div>}
                    {nextSteps.length > 0 && (
                        <div className="text-sm">
                            <div className="text-muted">Next steps</div>
                            <ul className="list-disc pl-5">
                                {nextSteps.map((step) => (
                                    <li key={step}>{step}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {hasWorkingNotes && (
                        <LemonCollapse
                            embedded
                            size="xsmall"
                            panels={[
                                {
                                    key: 'notes',
                                    header: "Agent's working notes",
                                    dataAttr: 'autoresearch-agent-working-notes',
                                    content: (
                                        <div className="space-y-1 text-xs text-muted">
                                            {distillation && <div>{distillation}</div>}
                                            {recommendedNext && <div>Next it plans to: {recommendedNext}</div>}
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    )}
                </>
            ) : (
                <>
                    {distillation && <div className="text-sm">{distillation}</div>}
                    {recommendedNext && <div className="text-sm text-muted">Next it plans to: {recommendedNext}</div>}
                </>
            )}
            <div className="text-xs text-muted">From run {runNumber}</div>
        </SectionCard>
    )
}
