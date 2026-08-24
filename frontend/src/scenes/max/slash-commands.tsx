import { IconActivity, IconMemory, IconRocket, IconSupport, IconThumbsUp } from '@posthog/icons'

import { FeatureFlagKey } from 'lib/constants'

import { SlashCommandName } from '~/queries/schema/schema-assistant-messages'

export { SlashCommandName }

export interface SlashCommand {
    name: SlashCommandName
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
    flag?: FeatureFlagKey
    /** If true, this command is only available when the conversation is idle (not streaming) */
    requiresIdle?: boolean
    /**
     * If true, this command is hidden for sandbox-runtime conversations.
     * Slash commands are handled by the LangGraph runtime; the sandbox runtime has no equivalent,
     * so a command left visible there reaches the agent as plain text instead of running.
     * LangGraph conversations are unaffected.
     */
    hiddenInSandbox?: boolean
}

export const MAX_SLASH_COMMANDS: SlashCommand[] = [
    {
        name: SlashCommandName.SlashInit,
        description: 'Set up knowledge about your product & business',
        icon: <IconRocket />,
        hiddenInSandbox: true,
    },
    {
        name: SlashCommandName.SlashRemember,
        arg: '[information]',
        description: "Add [information] to PostHog AI's project-level memory",
        icon: <IconMemory />,
        hiddenInSandbox: true,
    },
    {
        name: SlashCommandName.SlashUsage,
        description: 'View AI credit usage for this conversation and billing period',
        icon: <IconActivity />,
        hiddenInSandbox: true,
    },
    {
        name: SlashCommandName.SlashFeedback,
        arg: '[your feedback]',
        description: 'Share feedback about your PostHog AI experience',
        icon: <IconThumbsUp />,
        hiddenInSandbox: true,
    },
    {
        name: SlashCommandName.SlashTicket,
        description: 'Create a support ticket with a summary of this conversation',
        icon: <IconSupport />,
        requiresIdle: true,
        hiddenInSandbox: true,
    },
]
