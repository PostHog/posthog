import type { Meta, StoryObj } from '@storybook/react'

import { Slider } from './slider'

const meta = {
    title: 'Primitives/Slider',
    component: Slider,
    tags: ['autodocs'],
} satisfies Meta<typeof Slider>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return <Slider defaultValue={[75]} max={100} step={1} className="mx-auto w-full max-w-xs" />
    },
} satisfies Story

export const Vertical: Story = {
    render: () => {
        return <Slider defaultValue={[75]} max={100} step={1} className="mx-auto w-full max-w-xs" orientation="vertical" />
    },
} satisfies Story

export const Range: Story = {
    render: () => {
        return <Slider defaultValue={[75, 25]} max={100} step={1} className="mx-auto w-full max-w-md" />
    },
} satisfies Story

export const RangeVertical: Story = {
    render: () => {
        return <Slider defaultValue={[75, 25]} max={100} step={1} className="mx-auto w-full max-w-md" orientation="vertical" />
    },
} satisfies Story

export const Disabled: Story = {
    render: () => {
        return <Slider defaultValue={[75, 25]} max={100} step={1} className="mx-auto w-full max-w-md" disabled />
    },
} satisfies Story
