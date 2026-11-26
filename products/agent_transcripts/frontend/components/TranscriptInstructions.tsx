import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'
import { TranscriptAgentSteps } from './TranscriptAgentSteps'

export function TranscriptInstructions(): JSX.Element {
    const { selectedAgent } = useValues(agentTranscriptSceneLogic)
    const { reportPromptCopied } = useActions(agentTranscriptSceneLogic)

    if (!selectedAgent) {
        return (
            <Text size="sm" variant="muted" render={<p className="m-0" />}>
                Choose an agent to see how to get the transcript.
            </Text>
        )
    }

    return (
        <div className="flex flex-col gap-3" data-attr="agent-transcript-instructions">
            <TranscriptAgentSteps agent={selectedAgent} onCopy={reportPromptCopied} />
        </div>
    )
}
