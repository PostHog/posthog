import { TranscriptAgentEnumApi } from '../generated/api.schemas'

export const TRANSCRIPT_AGENT_LABELS: Record<TranscriptAgentEnumApi, string> = {
    [TranscriptAgentEnumApi.ClaudeCode]: 'Claude Code',
    [TranscriptAgentEnumApi.Codex]: 'Codex',
    [TranscriptAgentEnumApi.Cursor]: 'Cursor',
    [TranscriptAgentEnumApi.ClaudeApp]: 'Claude app',
    [TranscriptAgentEnumApi.Chatgpt]: 'ChatGPT',
    [TranscriptAgentEnumApi.Other]: 'Other',
}

export const TRANSCRIPT_AGENTS = Object.values(TranscriptAgentEnumApi)
