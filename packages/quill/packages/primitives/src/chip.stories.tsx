import type { Meta, StoryObj } from '@storybook/react'
import { TagIcon } from 'lucide-react'

import { Chip, ChipClose, ChipGroup } from './chip'

const meta: Meta<typeof Chip> = {
    title: 'Primitives/Chip',
    component: Chip,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => <Chip>Default</Chip>,
}

export const WithClose: Story = {
    render: () => (
        <Chip>
            Removable
            <ChipClose onClick={() => alert('removed')} />
        </Chip>
    ),
}

export const WithIcon: Story = {
    render: () => (
        <Chip>
            <TagIcon />
            Tagged
        </Chip>
    ),
}

export const WithIconAndClose: Story = {
    render: () => (
        <Chip>
            <TagIcon />
            Tagged
            <ChipClose onClick={() => alert('removed')} />
        </Chip>
    ),
}

export const Variants: Story = {
    render: () => (
        <div className="flex flex-wrap gap-2">
            <Chip variant="primary">Primary</Chip>
            <Chip variant="outline">Outline</Chip>
            <Chip>Default</Chip>
            <Chip variant="destructive">
                Destructive
                <ChipClose />
            </Chip>
        </div>
    ),
}

export const Sizes: Story = {
    render: () => (
        <div className="flex flex-wrap items-center gap-2">
            <Chip size="xs">Extra small</Chip>
            <Chip size="sm">Small</Chip>
            <Chip size="default">Default</Chip>
            <Chip size="lg">Large</Chip>
        </div>
    ),
}

export const Group: Story = {
    render: () => (
        <ChipGroup>
            <Chip>
                React
                <ChipClose />
            </Chip>
            <Chip>
                TypeScript
                <ChipClose />
            </Chip>
            <Chip>
                Tailwind
                <ChipClose />
            </Chip>
        </ChipGroup>
    ),
}

export const Disabled: Story = {
    render: () => (
        <Chip disabled>
            Disabled
            <ChipClose />
        </Chip>
    ),
}
