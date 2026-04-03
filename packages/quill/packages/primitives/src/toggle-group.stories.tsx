import type { Meta, StoryObj } from '@storybook/react-vite'
import { ToggleGroup, ToggleGroupItem } from './toggle-group'
import { IconFilter, IconHeart, IconSortAlpha } from '@posthog/icons'

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
                        <IconFilter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <IconHeart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <IconSortAlpha />
                    </ToggleGroupItem>
                </ToggleGroup>
                <ToggleGroup variant="outline" multiple size='sm'>
                    <ToggleGroupItem value="bold" aria-label="Toggle bold">
                        <IconFilter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <IconHeart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <IconSortAlpha />
                    </ToggleGroupItem>
                </ToggleGroup>
                <ToggleGroup variant="outline" multiple size='lg'>
                    <ToggleGroupItem value="bold" aria-label="Toggle bold">
                        <IconFilter />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="italic" aria-label="Toggle italic">
                        <IconHeart />
                    </ToggleGroupItem>
                    <ToggleGroupItem value="strikethrough" aria-label="Toggle strikethrough">
                        <IconSortAlpha />
                    </ToggleGroupItem>
                </ToggleGroup>
            </div>
        )
    },
} satisfies Story
