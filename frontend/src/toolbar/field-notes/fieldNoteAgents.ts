import { AGENT_DEEP_LINK_TARGETS } from 'lib/components/AgentPromptButton/agentDeepLinks'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export const CLIPBOARD_AGENT_KEY = 'clipboard'

export interface FieldNoteAgent {
    key: string
    name: string
}

/** Destinations offered by the field notes menu. The clipboard works without an installed app. */
export const FIELD_NOTE_AGENTS: FieldNoteAgent[] = [
    ...AGENT_DEEP_LINK_TARGETS.map(({ key, name }) => ({ key, name })),
    { key: CLIPBOARD_AGENT_KEY, name: 'Clipboard' },
]

export function fieldNoteAgentName(agentKey: string): string {
    return FIELD_NOTE_AGENTS.find((agent) => agent.key === agentKey)?.name ?? 'Clipboard'
}

/** Open the prompt in the chosen agent, falling back to the clipboard for an unknown key. */
export async function sendPromptToAgent(agentKey: string, prompt: string): Promise<void> {
    const target = AGENT_DEEP_LINK_TARGETS.find((agent) => agent.key === agentKey)
    if (!target) {
        await copyToClipboard(prompt, 'field notes prompt')
        return
    }
    window.open(target.buildUrl(prompt), '_blank')
}
