import type { Meta, StoryObj } from '@storybook/react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from './collapsible'

const meta = {
    title: 'Primitives/Collapsible',
    component: Collapsible,
    tags: ['autodocs'],
} satisfies Meta<typeof Collapsible>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Collapsible className="max-w-sm">
            <CollapsibleTrigger>
                <p>Collapsible Trigger</p>
            </CollapsibleTrigger>
            <CollapsibleContent>
                <p>Collapsible Content</p>
            </CollapsibleContent>
        </Collapsible>
    ),
} satisfies Story

export const Folder: Story = {
    render: () => (
        <Collapsible className="max-w-sm" variant="folder">
            <CollapsibleTrigger>
                <p>Collapsible Trigger</p>
            </CollapsibleTrigger>
            <CollapsibleContent>
            <Collapsible variant="folder">
                <CollapsibleTrigger>
                    <p>Collapsible Trigger</p>
                </CollapsibleTrigger>
                <CollapsibleContent>
                    <p>Collapsible Content</p>
                </CollapsibleContent>
            </Collapsible>
            </CollapsibleContent>
        </Collapsible>
    ),
} satisfies Story