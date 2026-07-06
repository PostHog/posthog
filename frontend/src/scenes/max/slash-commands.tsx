import { IconActivity, IconMemory, IconRocket, IconSupport, IconThumbsUp } from '@posthog/icons'

import { FeatureFlagKey } from 'lib/constants'

import { SlashCommandName } from '~/queries/schema/schema-assistant-messages'

import { SurfaceSlashCommand } from 'products/posthog_ai/frontend/api/slashCommands'

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
     * Core-memory commands (`/init`, `/remember`) are not yet supported under sandbox AI.
     * LangGraph conversations are unaffected.
     */
    hiddenInSandbox?: boolean
}

/**
 * A slash command from either registry: the LangGraph `MAX_SLASH_COMMANDS` (name typed as the
 * `SlashCommandName` enum) or the sandbox `SANDBOX_SLASH_COMMANDS` surface registry (name a plain
 * string). The shared consumers (`filteredCommands`, `selectCommand`/`activateCommand`,
 * `SlashCommandAutocomplete`) accept either.
 */
export type AnySlashCommand = SlashCommand | SurfaceSlashCommand

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
    },
    {
        name: SlashCommandName.SlashFeedback,
        arg: '[your feedback]',
        description: 'Share feedback about your PostHog AI experience',
        icon: <IconThumbsUp />,
    },
    {
        name: SlashCommandName.SlashTicket,
        description: 'Create a support ticket with a summary of this conversation',
        icon: <IconSupport />,
        requiresIdle: true,
    },
]
