import { Text } from '@posthog/quill'

import { TranscriptAgentEnumApi } from '../generated/api.schemas'
import { TRANSCRIPT_AGENT_LABELS } from '../logics/transcriptAgents'
import { TranscriptPrompt } from './TranscriptPrompt'

const SESSION_LOG_LOCATIONS: Partial<Record<TranscriptAgentEnumApi, string>> = {
    [TranscriptAgentEnumApi.ClaudeCode]: 'Claude Code keeps them under ~/.claude/projects/.',
    [TranscriptAgentEnumApi.Codex]: 'Codex keeps them under ~/.codex/sessions/.',
}

function sessionLogPrompt(location: string): string {
    return [
        'Find the transcript file for this session, the one where we set up PostHog.',
        location,
        'Copy only that session to ./posthog-session-log.jsonl.',
        'In the copy, replace API keys, tokens, passwords and .env values with [REDACTED].',
        "Don't upload anything. Tell me the file path when you're done.",
    ].join(' ')
}

const CONVERSATION_EXPORT_PROMPT =
    'Create a downloadable file called posthog-conversation.md with this whole conversation: every message from me and from you, in order, word for word, including any searches or tools you used. ' +
    "Don't summarize or leave anything out. Replace any passwords, API keys or tokens with [REDACTED]."

const FILE_NAME_CLASS = 'rounded-sm bg-muted px-1 py-0.5 font-mono text-xs'

export interface TranscriptAgentStepsProps {
    agent: TranscriptAgentEnumApi
    /** Called after a prompt reaches the clipboard. */
    onCopy: () => void
}

export function TranscriptAgentSteps({ agent, onCopy }: TranscriptAgentStepsProps): JSX.Element {
    const label = TRANSCRIPT_AGENT_LABELS[agent]
    const sessionLogLocation = SESSION_LOG_LOCATIONS[agent]

    if (sessionLogLocation) {
        return (
            <>
                <Text size="sm" render={<p className="m-0" />}>
                    Paste this prompt into the <span>{label}</span> session where you set up PostHog. If you closed it,
                    resume it first.
                </Text>
                <TranscriptPrompt prompt={sessionLogPrompt(sessionLogLocation)} onCopy={onCopy} />
                <Text size="sm" render={<p className="m-0" />}>
                    Then upload the file it creates, <code className={FILE_NAME_CLASS}>posthog-session-log.jsonl</code>.
                </Text>
            </>
        )
    }

    if (agent === TranscriptAgentEnumApi.Cursor) {
        return (
            <Text size="sm" render={<ol className="m-0 flex list-decimal flex-col gap-1 pl-5" />}>
                <li>Open the Cursor chat where the agent set up PostHog.</li>
                <li>
                    Open the chat's menu and choose <strong>Export chat</strong>.
                </li>
                <li>Save the Markdown file. Remove any passwords, API keys or tokens from it, then upload it below.</li>
            </Text>
        )
    }

    if (agent === TranscriptAgentEnumApi.ClaudeApp || agent === TranscriptAgentEnumApi.Chatgpt) {
        return (
            <>
                <Text size="sm" render={<p className="m-0" />}>
                    Paste this prompt into the same <span>{label}</span> conversation where you set up PostHog.
                </Text>
                <TranscriptPrompt prompt={CONVERSATION_EXPORT_PROMPT} onCopy={onCopy} />
                <Text size="sm" render={<p className="m-0" />}>
                    Then download the file it creates, <code className={FILE_NAME_CLASS}>posthog-conversation.md</code>,
                    and upload it below.
                </Text>
            </>
        )
    }

    return (
        <Text size="sm" render={<p className="m-0" />}>
            Export or save the conversation as a text, Markdown or JSON file. Remove any passwords, API keys or tokens
            from it, then upload it below.
        </Text>
    )
}
