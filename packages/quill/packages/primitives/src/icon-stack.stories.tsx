import type { Meta, StoryObj } from '@storybook/react'
import { Folder, LayoutDashboard, NotebookText, Palette } from 'lucide-react'
import * as React from 'react'

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from './empty'
import { IconStack, IconStackItem } from './icon-stack'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, createTooltipHandle } from './tooltip'

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

const ITEMS = [
    { key: 'canvas', label: 'Open the canvas', color: '#7c3aed', icon: <Palette /> },
    { key: 'notebook', label: 'Open the notebook', color: '#ef4444', icon: <NotebookText /> },
    { key: 'dashboard', label: 'Open the dashboard', color: '#ff8b07', icon: <LayoutDashboard /> },
    { key: 'folder', label: 'Open the folder', icon: <Folder /> },
]

export const Interactive: Story = {
    render: () => {
        return (
            <p className="text-sm">
                Four things need you today{' '}
                <IconStack className="ml-2 align-middle">
                    {ITEMS.map((item) => (
                        <IconStackItem
                            key={item.key}
                            color={item.color}
                            render={<button type="button" aria-label={item.label} />}
                        >
                            {item.icon}
                        </IconStackItem>
                    ))}
                </IconStack>
            </p>
        )
    },
}

function ActiveOnHoverStory(): React.ReactElement {
    const [hoveredKey, setHoveredKey] = React.useState<string | null>(null)
    return (
        <div className="flex flex-col gap-4 text-sm">
            <p>
                Four things need you today{' '}
                <IconStack className="ml-2 align-middle">
                    {ITEMS.map((item) => (
                        <IconStackItem
                            key={item.key}
                            color={item.color}
                            active={hoveredKey === item.key}
                            render={<button type="button" aria-label={item.label} />}
                        >
                            {item.icon}
                        </IconStackItem>
                    ))}
                </IconStack>
            </p>
            <ul className="flex flex-col gap-1">
                {ITEMS.map((item) => (
                    <li
                        key={item.key}
                        className="w-fit cursor-default rounded px-2 py-1 hover:bg-muted"
                        onMouseEnter={() => setHoveredKey(item.key)}
                        onMouseLeave={() => setHoveredKey(null)}
                    >
                        {item.label}
                    </li>
                ))}
            </ul>
        </div>
    )
}

export const ActiveOnHover: Story = {
    render: () => <ActiveOnHoverStory />,
}

function WithTooltipsStory(): React.ReactElement {
    const [tooltip] = React.useState(() => createTooltipHandle<string>())
    return (
        <TooltipProvider>
            <p className="text-sm">
                Four things need you today{' '}
                <IconStack className="ml-2 align-middle">
                    {ITEMS.map((item) => (
                        <IconStackItem
                            key={item.key}
                            color={item.color}
                            render={
                                <TooltipTrigger
                                    handle={tooltip}
                                    payload={item.label}
                                    render={<button type="button" aria-label={item.label} />}
                                />
                            }
                        >
                            {item.icon}
                        </IconStackItem>
                    ))}
                </IconStack>
            </p>
            <Tooltip handle={tooltip}>{({ payload }) => <TooltipContent>{payload}</TooltipContent>}</Tooltip>
        </TooltipProvider>
    )
}

export const WithTooltips: Story = {
    render: () => <WithTooltipsStory />,
}
