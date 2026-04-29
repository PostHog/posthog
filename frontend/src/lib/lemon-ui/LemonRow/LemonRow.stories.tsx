import type { Meta, StoryObj } from '@storybook/react'

import { IconInfo } from '@posthog/icons'

import { IconPremium } from 'lib/lemon-ui/icons'

import { LemonRow, LemonRowProps } from './LemonRow'

type Story = StoryObj<LemonRowProps>
const meta: Meta<LemonRowProps> = {
    title: 'Lemon UI/Lemon Row',
    component: LemonRow as any,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    args: {
        children: 'Information',
        icon: <IconPremium />,
    },
}

export const TextOnly: Story = {
    args: {
        ...Default.args,
        icon: null,
    },
}

export const IconOnly: Story = {
    args: {
        ...Default.args,
        children: null,
    },
}

export const Outlined: Story = {
    args: {
        ...Default.args,
        outlined: true,
    },
}

export const Success: Story = {
    args: {
        ...Default.args,
        status: 'success',
    },
}

export const Warning: Story = {
    args: {
        ...Default.args,
        status: 'warning',
    },
}

export const Danger: Story = {
    args: {
        ...Default.args,
        status: 'danger',
    },
}

export const Disabled: Story = {
    args: {
        ...Default.args,
        disabled: true,
    },
}

export const Loading: Story = {
    args: {
        ...Default.args,
        loading: true,
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

export const Small: Story = {
    args: {
        ...Default.args,
        outlined: true,
        size: 'small',
    },
}

export const Tall: Story = {
    args: {
        ...Default.args,
        outlined: true,
        size: 'tall',
    },
}

export const Large: Story = {
    args: {
        ...Default.args,
        outlined: true,
        size: 'large',
    },
}

export const FullWidth: Story = {
    args: {
        ...Default.args,
        outlined: true,
        fullWidth: true,
    },
}

export const WithSideIcon: Story = {
    args: {
        ...Default.args,
        sideIcon: <IconInfo />,
    },
}

export const WithTooltip: Story = {
    args: {
        ...Default.args,
        tooltip:
            'The lifespan of kangaroos averages at six years in the wild to in excess of 20 years in captivity, varying by the species.',
    },
}

export const WithExtendedContent: Story = {
    args: {
        ...Default.args,
        type: 'stealth',
        extendedContent: "This is some extra info about this particular item. Hopefully it's helpful.",
    },
}
