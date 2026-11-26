import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import type { TranscriptAgentEnumApi } from '../generated/api.schemas'
import { TRANSCRIPT_AGENTS, TRANSCRIPT_AGENT_LABELS } from '../logics/transcriptAgents'
import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'

const AGENT_GAP = 2

export function TranscriptAgentPicker(): JSX.Element {
    const { selectedAgent } = useValues(agentTranscriptSceneLogic)
    const { selectAgent } = useActions(agentTranscriptSceneLogic)

    return (
        <ToggleGroup
            aria-label="Which agent did you use?"
            variant="outline"
            spacing={AGENT_GAP}
            className="w-full flex-wrap"
            value={selectedAgent ? [selectedAgent] : []}
            onValueChange={(next: string[]) => {
                // Pressing the chosen agent again would clear the choice, and the steps below need one.
                if (next[0]) {
                    selectAgent(next[0] as TranscriptAgentEnumApi)
                }
            }}
            data-attr="agent-transcript-agent-picker"
        >
            {TRANSCRIPT_AGENTS.map((agent) => (
                <ToggleGroupItem key={agent} value={agent} data-attr={`agent-transcript-agent-${agent}`}>
                    {agent === selectedAgent && <IconCheck />}
                    <span>{TRANSCRIPT_AGENT_LABELS[agent]}</span>
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
