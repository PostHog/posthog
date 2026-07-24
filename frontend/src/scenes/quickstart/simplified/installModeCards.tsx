import { IconBook, IconGithub, IconTerminal } from '@posthog/icons'

export type QuickstartInstallMode = 'cloud' | 'local' | 'manual'

export const INSTALL_MODE_CARDS: {
    value: QuickstartInstallMode
    title: string
    description: string
    icon: JSX.Element
}[] = [
    {
        value: 'cloud',
        title: 'Agent opens a pull request',
        description: 'We run the setup agent on your repo. Review the PR and merge it.',
        icon: <IconGithub />,
    },
    {
        value: 'local',
        title: 'Agent runs in your terminal',
        description: 'One command. It edits your code locally and you commit. We pay for the inference.',
        icon: <IconTerminal />,
    },
    {
        value: 'manual',
        title: 'Install it yourself',
        description: 'Follow the SDK guide for your framework.',
        icon: <IconBook />,
    },
]
