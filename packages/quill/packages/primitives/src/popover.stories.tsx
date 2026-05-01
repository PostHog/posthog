import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { Button } from './button'
import { Popover, PopoverContent, PopoverTrigger } from './popover'

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
