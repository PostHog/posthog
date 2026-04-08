import type { Meta, StoryObj } from '@storybook/react'
import { Bold, Italic, XIcon } from 'lucide-react'

import { Toggle } from './toggle'

const meta = {
    title: 'Primitives/Toggle',
    component: Toggle,
    tags: ['autodocs'],
} satisfies Meta<typeof Toggle>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <Toggle variant="outline" size="icon">
                <Bold />
            </Toggle>
        )
    },
} satisfies Story

export const WithText: Story = {
    render: () => {
        return (
            <Toggle variant="outline">
                <Italic />
                Italic
            </Toggle>
        )
    },
} satisfies Story

export const Disabled: Story = {
    render: () => {
        return (
            <Toggle aria-label="Toggle disabled" disabled>
                <XIcon />
                Disabled
            </Toggle>
        )
    },
} satisfies Story
