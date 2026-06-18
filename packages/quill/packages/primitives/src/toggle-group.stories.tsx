import type { Meta, StoryObj } from '@storybook/react'
import { Filter, Heart, ArrowDownAZ } from 'lucide-react'

import { ToggleGroup, ToggleGroupItem } from './toggle-group'

const meta = {
    title: 'Primitives/Toggle Group',
    component: ToggleGroup,
    tags: ['autodocs'],
} satisfies Meta<typeof ToggleGroup>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <div className="flex gap-2">
                <ToggleGroup variant="outline" multiple>
                    <ToggleGroupItem value="bold" aria-label="Toggle bold">
                        <Filter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <Heart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <ArrowDownAZ />
                    </ToggleGroupItem>
                </ToggleGroup>
                <ToggleGroup variant="outline" multiple size="sm">
                    <ToggleGroupItem value="bold" aria-label="Toggle bold">
                        <Filter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <Heart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <ArrowDownAZ />
                    </ToggleGroupItem>
                </ToggleGroup>
                <ToggleGroup variant="outline" multiple size="lg">
                    <ToggleGroupItem value="bold" aria-label="Toggle bold">
                        <Filter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <Heart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <ArrowDownAZ />
                    </ToggleGroupItem>
                </ToggleGroup>
            </div>
        )
    },
} satisfies Story

export const Vertical: Story = {
    render: () => {
        return (
            <div className="flex gap-2">
                <ToggleGroup variant="outline" multiple orientation="vertical">
                    <ToggleGroupItem value="bold" aria-label="Toggle bold">
                        <Filter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <Heart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <ArrowDownAZ />
                    </ToggleGroupItem>
                </ToggleGroup>
            </div>
        )
    },
} satisfies Story

