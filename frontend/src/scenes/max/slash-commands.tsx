import { IconActivity, IconMemory, IconRocket, IconThumbsUp } from '@posthog/icons'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'

import { SlashCommandName } from '~/queries/schema/schema-assistant-messages'

export { SlashCommandName }

export interface SlashCommand {
    name: SlashCommandName
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
    flag?: FeatureFlagKey
}

export const MAX_SLASH_COMMANDS: SlashCommand[] = [
    {
        name: SlashCommandName.SlashInit,
        description: 'Set up knowledge about your product & business',
        icon: <IconRocket />,
    },
    {
        name: SlashCommandName.SlashRemember,
        arg: '[information]',
        description: "Add [information] to PostHog AI's project-level memory",
        icon: <IconMemory />,
    },
    {
        name: SlashCommandName.SlashUsage,
        description: 'View AI credit usage for this conversation',
        icon: <IconActivity />,
        flag: FEATURE_FLAGS.POSTHOG_AI_BILLING_USAGE_COMMAND,
    },
    {
        name: SlashCommandName.SlashFeedback,
        arg: '[your feedback]',
        description: 'Share feedback about your PostHog AI experience',
        icon: <IconThumbsUp />,
        flag: FEATURE_FLAGS.POSTHOG_AI_FEEDBACK_COMMAND,
    },
]
