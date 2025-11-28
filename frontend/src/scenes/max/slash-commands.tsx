import { IconActivity, IconMemory, IconRocket } from '@posthog/icons'

import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'

export interface SlashCommand {
    name: `/${string}`
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
    flag?: FeatureFlagKey
}

export const MAX_SLASH_COMMANDS: SlashCommand[] = [
    {
        name: '/init',
        description: 'Set up knowledge about your product & business',
        icon: <IconRocket />,
    },
    {
        name: '/remember',
        arg: '[information]',
        description: "Add [information] to PostHog AI's project-level memory",
        icon: <IconMemory />,
    },
    {
        name: '/usage',
        description: 'View AI credit usage for this conversation',
        icon: <IconActivity />,
        flag: FEATURE_FLAGS.POSTHOG_AI_BILLING_USAGE_COMMAND,
    },
]
