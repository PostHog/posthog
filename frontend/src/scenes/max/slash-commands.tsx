import { IconMemory, IconRocket } from '@posthog/icons'

export interface SlashCommand {
    name: `/${string}`
    arg?: `[${string}]`
    description: string
    icon: JSX.Element
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
        description: "Add [information] to Max's project-level memory",
        icon: <IconMemory />,
    },
]
