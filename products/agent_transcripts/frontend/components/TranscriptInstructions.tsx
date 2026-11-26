import { useActions, useValues } from 'kea'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { TRANSCRIPT_AGENTS, TRANSCRIPT_AGENT_LABELS } from '../logics/transcriptAgents'
import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'
import { TranscriptAgentSteps } from './TranscriptAgentSteps'

export function TranscriptInstructions(): JSX.Element {
    const { selectedAgent } = useValues(agentTranscriptSceneLogic)
    const { selectAgent, reportPromptCopied } = useActions(agentTranscriptSceneLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonRadio
                aria-label="Which agent did you use?"
                orientation="horizontal"
                className="flex-wrap gap-y-2"
                value={selectedAgent ?? undefined}
                onChange={selectAgent}
                options={TRANSCRIPT_AGENTS.map((agent) => ({
                    value: agent,
                    label: TRANSCRIPT_AGENT_LABELS[agent],
                    'data-attr': `agent-transcript-agent-${agent}`,
                }))}
                data-attr="agent-transcript-agent-picker"
            />
            {selectedAgent ? (
                <div className="flex flex-col gap-2" data-attr="agent-transcript-instructions">
                    <TranscriptAgentSteps agent={selectedAgent} onCopy={reportPromptCopied} />
                </div>
            ) : (
                <p className="m-0 text-secondary">Choose an agent to see how to get the transcript.</p>
            )}
        </div>
    )
}
