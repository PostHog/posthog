import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Button } from './button'
import { Popover, PopoverArrow, PopoverContent, PopoverTrigger } from './popover'

const meta = {
    title: 'Primitives/Popover',
    component: Popover,
    tags: ['autodocs'],
} satisfies Meta<typeof Popover>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        return (
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger render={<Button onClick={() => setOpen(true)}>Open Popover</Button>} />
                <PopoverContent align="start" side="bottom">
                    <p>Popover content</p>
                </PopoverContent>
            </Popover>
        )
    },
} satisfies Story

export const WithArrow: Story = {
    render: () => (
        <div className="flex flex-col items-center gap-24 py-24">
            {(['top', 'right', 'bottom', 'left'] as const).map((side) => (
                <Popover key={side} open>
                    <PopoverTrigger render={<Button variant="outline">{side}</Button>} />
                    <PopoverContent side={side} arrow className="w-48">
                        <p>Points back at the trigger.</p>
                    </PopoverContent>
                </Popover>
            ))}
        </div>
    ),
} satisfies Story

// the arrow inherits the popup's border and background, so a restyled popover keeps its arrow
export const WithCustomBorder: Story = {
    render: () => (
        <div className="flex items-center justify-center p-24">
            <Popover open>
                <PopoverTrigger render={<Button variant="outline">Open</Button>} />
                <PopoverContent side="bottom" arrow className="w-56 rounded-lg border-2 border-primary">
                    <p>Artifacts placed here</p>
                </PopoverContent>
            </Popover>
        </div>
    ),
} satisfies Story

// PopoverArrow is exported for popovers that compose their own content order
export const WithComposedArrow: Story = {
    render: () => (
        <div className="flex items-center justify-center p-24">
            <Popover open>
                <PopoverTrigger render={<Button variant="outline">Open</Button>} />
                <PopoverContent side="bottom" sideOffset={8} className="w-48">
                    <PopoverArrow />
                    <p>Arrow placed by hand.</p>
                </PopoverContent>
            </Popover>
        </div>
    ),
} satisfies Story
