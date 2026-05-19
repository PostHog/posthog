import type { Meta, StoryObj } from '@storybook/react'
import React from 'react'

import {
    NumberFieldRoot,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldIncrement,
    NumberFieldDecrement,
    NumberFieldScrubArea,
    NumberFieldScrubAreaCursor,
} from './number-field'

const meta = {
    title: 'Primitives/NumberField',
    component: NumberFieldRoot,
    tags: ['autodocs'],
} satisfies Meta<typeof NumberFieldRoot>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        const [value, setValue] = React.useState<number | null>(25)
        return (
            <div className="max-w-32">
                <NumberFieldRoot value={value} onValueChange={setValue}>
                    <NumberFieldGroup>
                        <NumberFieldDecrement />
                        <NumberFieldInput />
                        <NumberFieldIncrement />
                    </NumberFieldGroup>
                </NumberFieldRoot>
            </div>
        )
    },
}

export const WithMinMax: Story = {
    render: () => {
        const [value, setValue] = React.useState<number | null>(5)
        return (
            <div className="max-w-32">
                <NumberFieldRoot value={value} onValueChange={setValue} min={0} max={59} step={1}>
                    <NumberFieldGroup>
                        <NumberFieldDecrement />
                        <NumberFieldInput />
                        <NumberFieldIncrement />
                    </NumberFieldGroup>
                </NumberFieldRoot>
            </div>
        )
    },
}

export const WithScrubArea: Story = {
    render: () => {
        const [value, setValue] = React.useState<number | null>(50)
        return (
            <div className="max-w-32">
                <NumberFieldRoot value={value} onValueChange={setValue}>
                    <NumberFieldScrubArea>
                        <label className="text-xs text-muted-foreground cursor-ew-resize">Amount</label>
                        <NumberFieldScrubAreaCursor />
                    </NumberFieldScrubArea>
                    <NumberFieldGroup>
                        <NumberFieldDecrement />
                        <NumberFieldInput />
                        <NumberFieldIncrement />
                    </NumberFieldGroup>
                </NumberFieldRoot>
            </div>
        )
    },
}

export const SmallCompact: Story = {
    render: () => {
        const [value, setValue] = React.useState<number | null>(12)
        return (
            <div className="max-w-20">
                <NumberFieldRoot value={value} onValueChange={setValue} min={0} max={23}>
                    <NumberFieldGroup className="h-6">
                        <NumberFieldDecrement />
                        <NumberFieldInput className="text-[10px]" />
                        <NumberFieldIncrement />
                    </NumberFieldGroup>
                </NumberFieldRoot>
            </div>
        )
    },
}
