import { Meta, StoryFn } from '@storybook/react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { KeyboardShortcut } from './KeyboardShortcut'

const meta: Meta<typeof KeyboardShortcut> = {
    title: 'PostHog 3000/Keyboard Shortcut',
    component: KeyboardShortcut,
    tags: ['autodocs'],
}
export default meta

export const Default = {
    args: {
        cmd: true,
        shift: true,
        k: true,
    },
}

export const WithinTooltip: StoryFn = () => {
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
}
