import { Meta, StoryObj } from '@storybook/react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { KeyboardShortcut, KeyboardShortcutProps } from './KeyboardShortcut'

const meta: Meta<KeyboardShortcutProps> = {
    title: 'PostHog 3000/Keyboard Shortcut',
    component: KeyboardShortcut,
    tags: ['autodocs'],
}
type Story = StoryObj<KeyboardShortcutProps>
export default meta

export const Default: Story = {
    args: {
        command: true,
        shift: true,
        k: true,
    },
}

export const WithinTooltip: Story = {
    render: () => {
        return (
            <Tooltip
                title={
                    <>
                        Press <KeyboardShortcut command shift k /> to create a new feature flag
                    </>
                }
                placement="right"
                visible
            >
                <IconInfo className="text-2xl" />
            </Tooltip>
        )
    },
}
