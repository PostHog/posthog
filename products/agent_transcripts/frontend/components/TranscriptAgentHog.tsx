import { TranscriptAgentEnumApi } from '../generated/api.schemas'
import { ChatAppHog, CursorHog, OtherAgentHog, TerminalAgentHog } from './transcriptHogs'

const AGENT_HOGS: Record<TranscriptAgentEnumApi, typeof TerminalAgentHog> = {
    [TranscriptAgentEnumApi.ClaudeCode]: TerminalAgentHog,
    [TranscriptAgentEnumApi.Codex]: TerminalAgentHog,
    [TranscriptAgentEnumApi.Cursor]: CursorHog,
    [TranscriptAgentEnumApi.ClaudeApp]: ChatAppHog,
    [TranscriptAgentEnumApi.Chatgpt]: ChatAppHog,
    [TranscriptAgentEnumApi.Other]: OtherAgentHog,
}

export interface TranscriptAgentHogProps {
    agent: TranscriptAgentEnumApi | null
}

/** The hedgehog for the "get the transcript" step, which matches the kind of agent chosen. */
export function TranscriptAgentHog({ agent }: TranscriptAgentHogProps): JSX.Element {
    const Hog = agent ? AGENT_HOGS[agent] : TerminalAgentHog

    return <Hog className="size-full" loading="eager" />
}
