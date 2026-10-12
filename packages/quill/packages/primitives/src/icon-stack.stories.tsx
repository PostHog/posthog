import type { Meta, StoryObj } from '@storybook/react'
import { Folder, LayoutDashboard, NotebookText, Palette } from 'lucide-react'

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from './empty'
import { IconStack, IconStackItem } from './icon-stack'

const meta: Meta<typeof IconStack> = {
    title: 'Primitives/IconStack',
    component: IconStack,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

export const InEmpty: Story = {
    render: () => {
        return (
            <div className="flex gap-4">
                <Empty>
                    <EmptyHeader>
                        <IconStack>
                            <IconStackItem color="#7c3aed">
                                <Palette />
                            </IconStackItem>
                            <IconStackItem color="#ef4444">
                                <NotebookText />
                            </IconStackItem>
                            <IconStackItem color="#ff8b07">
                                <LayoutDashboard />
                            </IconStackItem>
                        </IconStack>
                        <EmptyTitle>Notebooks are in Views</EmptyTitle>
                        <EmptyDescription>One colored tile per product the empty state is about.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
                <Empty>
                    <EmptyHeader>
                        <IconStack>
                            <IconStackItem>
                                <Folder />
                            </IconStackItem>
                        </IconStack>
                        <EmptyTitle>No files yet</EmptyTitle>
                        <EmptyDescription>No product, so the tile stays grey.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    },
}

export const Interactive: Story = {
    render: () => {
        return (
            <p className="text-sm">
                Three things need you today{' '}
                <IconStack className="ml-2 align-middle">
                    <IconStackItem color="#7c3aed" render={<button type="button" aria-label="Open the canvas" />}>
                        <Palette />
                    </IconStackItem>
                    <IconStackItem
                        color="#ef4444"
                        active
                        render={<button type="button" aria-label="Open the notebook" />}
                    >
                        <NotebookText />
                    </IconStackItem>
                    <IconStackItem color="#ff8b07" render={<button type="button" aria-label="Open the dashboard" />}>
                        <LayoutDashboard />
                    </IconStackItem>
                </IconStack>
            </p>
        )
    },
}
