import type { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { Link, LinkProps } from './Link'

type Story = StoryObj<LinkProps>
const meta: Meta<LinkProps> = {
    title: 'Lemon UI/Link',
    component: Link as any,
    args: {
        children: 'Click me',
    },
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    args: {},
}

export const ToLink: Story = {
    args: {
        to: urls.projectHomepage(),
    },
}

export const DisabledWithReason: Story = {
    args: {
        disabledReason: 'Not allowed',
    },
}
