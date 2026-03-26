import type { Meta, StoryObj } from '@storybook/react'

import { urls } from 'scenes/urls'

import { Link } from './Link'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof Link> = {
    title: 'Lemon UI/Link',
    component: Link,
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
