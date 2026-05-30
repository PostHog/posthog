import { IconActivity, IconMemory, IconRocket, IconSupport, IconThumbsUp } from '@posthog/icons'

import { FeatureFlagKey } from 'lib/constants'

import { SlashCommandName } from '~/queries/schema/schema-assistant-messages'

export { SlashCommandName }

/** Shown on disabled sandbox-runtime slash commands; also the gate the autocomplete + activation key off. */
export const SANDBOX_UNSUPPORTED_TOOLTIP = 'Not yet supported in sandbox AI'

export interface SlashCommand {
    name: SlashCommandName
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
    flag?: FeatureFlagKey
    /** If true, this command is only available when the conversation is idle (not streaming) */
    requiresIdle?: boolean
    /** If true, this command is only available for users on paid plans or with an active trial */
    requiresPaidPlan?: boolean
    /**
     * If true, this command is a no-op for sandbox-runtime conversations and renders disabled with the
     * "Not yet supported in sandbox AI" tooltip (02_CORE § 8). LangGraph behavior is unchanged.
     */
    unsupportedInSandbox?: boolean
}

export const MAX_SLASH_COMMANDS: SlashCommand[] = [
    {
        name: SlashCommandName.SlashInit,
        description: 'Set up knowledge about your product & business',
        icon: <IconRocket />,
        unsupportedInSandbox: true,
    },
    {
        name: SlashCommandName.SlashRemember,
        arg: '[information]',
        description: "Add [information] to PostHog AI's project-level memory",
        icon: <IconMemory />,
        unsupportedInSandbox: true,
    },
    {
        name: SlashCommandName.SlashUsage,
        description: 'View AI credit usage for this conversation',
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
        requiresPaidPlan: true,
    },
]
