import type { Meta, StoryObj } from '@storybook/react'

import { IconBug, IconInfo, IconSearch } from '@posthog/icons'

import { AgentPromptButton } from './AgentPromptButton'

const meta = {
    title: 'Components/AgentPromptButton',
    component: AgentPromptButton,
    parameters: {
        layout: 'centered',
    },
} satisfies Meta<typeof AgentPromptButton>

export default meta
type Story = StoryObj<typeof meta>

const ERROR_ACTIONS = [
    {
        key: 'fix',
        label: 'Fix',
        icon: <IconBug />,
        buildPrompt: () =>
            'Please help me fix the root cause of this error. Here is the stack trace:\n\n```\nTypeError: Cannot read properties of undefined (reading "map")\n  at UserList.render (UserList.tsx:42)\n```',
    },
    {
        key: 'investigate',
        label: 'Investigate',
        icon: <IconSearch />,
        buildPrompt: () =>
            'Please help me investigate this error and understand what is happening. Here is the stack trace:\n\n```\nTypeError: Cannot read properties of undefined (reading "map")\n  at UserList.render (UserList.tsx:42)\n```',
    },
    {
        key: 'explain',
        label: 'Explain',
        icon: <IconInfo />,
        buildPrompt: () =>
            'Please explain this error in depth. What causes it and what are the possible remedies?\n\n```\nTypeError: Cannot read properties of undefined (reading "map")\n  at UserList.render (UserList.tsx:42)\n```',
    },
]

export const Default: Story = {
    args: {
        actions: ERROR_ACTIONS,
        storageKey: 'story-agent-prompt-button',
    },
}

export const OpenDropdown: Story = {
    args: {
        actions: ERROR_ACTIONS,
        storageKey: 'story-agent-open-dropdown',
        defaultOpen: true,
    },
    parameters: {
        // Radix portals the dropdown content into document.body, outside #storybook-root,
        // so snapshot the whole body to include it.
        testOptions: { snapshotTargetSelector: 'body' },
    },
}

export const SingleAction: Story = {
    args: {
        actions: [
            {
                key: 'fix',
                label: 'Fix',
                icon: <IconBug />,
                buildPrompt: () => 'Fix this error.',
            },
        ],
        storageKey: 'story-agent-single',
    },
}

export const SizeVariants: Story = {
    args: { actions: ERROR_ACTIONS },
    render: (): JSX.Element => (
        <div className="flex flex-col items-start gap-2">
            {(['xs', 'sm', 'default', 'lg'] as const).map((size) => (
                <AgentPromptButton
                    key={size}
                    actions={ERROR_ACTIONS}
                    storageKey={`story-agent-size-${size}`}
                    size={size}
                />
            ))}
        </div>
    ),
}

export const IntentVariants: Story = {
    args: { actions: ERROR_ACTIONS },
    render: (): JSX.Element => (
        <div className="flex flex-col items-start gap-2">
            {(['default', 'primary', 'outline', 'destructive', 'link-muted'] as const).map((variant) => (
                <AgentPromptButton
                    key={variant}
                    actions={ERROR_ACTIONS}
                    storageKey={`story-agent-variant-${variant}`}
                    variant={variant}
                />
            ))}
        </div>
    ),
}
