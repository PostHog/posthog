import type { Meta, StoryObj } from '@storybook/react'

import { Separator } from './separator'

const meta = {
    title: 'Primitives/Separator',
    component: Separator,
    tags: ['autodocs'],
} satisfies Meta<typeof Separator>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        return (
            <div className="flex max-w-sm flex-col gap-4 text-sm">
                <div className="flex flex-col gap-1.5">
                    <div className="leading-none font-medium">quill/primitives</div>
                    <div className="text-muted-foreground">Bringing unity to PostHog UI universe</div>
                </div>
                <Separator />
                <div>A separator is a line that separates content.</div>
            </div>
        )
    },
} satisfies Story

export const Vertical: Story = {
    render: () => {
        return (
            <div className="flex h-5 items-center gap-4 text-sm">
                <div>Blog</div>
                <Separator orientation="vertical" />
                <div>Docs</div>
                <Separator orientation="vertical" />
                <div>Source</div>
            </div>
        )
    },
} satisfies Story
