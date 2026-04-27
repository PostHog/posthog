import type { Meta, StoryObj } from '@storybook/react'

import { ScrollArea } from './scroll-area'

const meta = {
    title: 'Primitives/ScrollArea',
    component: ScrollArea,
    tags: ['autodocs'],
} satisfies Meta<typeof ScrollArea>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <ScrollArea className="h-[50vh] px-4">
            {Array.from({ length: 10 }).map((_, index) => (
                <p key={index} className="mb-4 leading-normal">
                    Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore
                    et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
                    aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse
                    cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in
                    culpa qui officia deserunt mollit anim id est laborum.
                </p>
            ))}
        </ScrollArea>
    ),
} satisfies Story

export const Horizontal: Story = {
    render: () => (
        <ScrollArea className="h-28 w-80 max-w-[calc(100vw-8rem)]">
            <ul className="m-0 flex list-none gap-3 p-0">
                {Array.from({ length: 20 }, (_, i) => (
                    <li
                        key={i}
                        className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg bg-muted text-sm font-bold text-gray-600 dark:text-gray-400"
                    >
                        {i + 1}
                    </li>
                ))}
            </ul>
        </ScrollArea>
    ),
} satisfies Story

export const AllDirections: Story = {
    render: () => (
        <ScrollArea className="h-80 w-80 max-w-[calc(100vw-8rem)]">
            <ul className="m-0 grid list-none grid-cols-[repeat(10,6.25rem)] grid-rows-[repeat(10,6.25rem)] gap-3 p-0">
                {Array.from({ length: 100 }, (_, i) => (
                    <li
                        key={i}
                        className="flex items-center justify-center rounded-lg bg-muted text-sm font-bold text-gray-600 dark:text-gray-400"
                    >
                        {i + 1}
                    </li>
                ))}
            </ul>
        </ScrollArea>
    ),
} satisfies Story

export const AlwaysShowScrollbars: Story = {
    render: () => (
        <ScrollArea alwaysShowScrollbars className="h-80 w-80 max-w-[calc(100vw-8rem)]">
            <ul className="m-0 grid list-none grid-cols-[repeat(10,6.25rem)] grid-rows-[repeat(10,6.25rem)] gap-3 p-0">
                {Array.from({ length: 100 }, (_, i) => (
                    <li
                        key={i}
                        className="flex items-center justify-center rounded-lg bg-muted text-sm font-bold text-gray-600 dark:text-gray-400"
                    >
                        {i + 1}
                    </li>
                ))}
            </ul>
        </ScrollArea>
    ),
} satisfies Story

export const ScrollToButtonVertical: Story = {
    render: () => (
        <ScrollArea showScrollToButton={['top', 'bottom']} className="h-[50vh] px-4">
            {Array.from({ length: 10 }).map((_, index) => (
                <p key={index} className="mb-4 leading-normal">
                    Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore
                    et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
                    aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse
                    cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in
                    culpa qui officia deserunt mollit anim id est laborum.
                </p>
            ))}
        </ScrollArea>
    ),
} satisfies Story

export const ScrollToButtonAllDirections: Story = {
    render: () => (
        <ScrollArea showScrollToButton="all" className="h-80 w-80 max-w-[calc(100vw-8rem)]">
            <ul className="m-0 grid list-none grid-cols-[repeat(10,6.25rem)] grid-rows-[repeat(10,6.25rem)] gap-3 p-0">
                {Array.from({ length: 100 }, (_, i) => (
                    <li
                        key={i}
                        className="flex items-center justify-center rounded-lg bg-muted text-sm font-bold text-gray-600 dark:text-gray-400"
                    >
                        {i + 1}
                    </li>
                ))}
            </ul>
        </ScrollArea>
    ),
} satisfies Story

export const HideScrollbarsAllDirections: Story = {
    render: () => (
        <ScrollArea hideScrollbars className="h-80 w-80 max-w-[calc(100vw-8rem)]">
            <ul className="m-0 grid list-none grid-cols-[repeat(10,6.25rem)] grid-rows-[repeat(10,6.25rem)] gap-3 p-0">
                {Array.from({ length: 100 }, (_, i) => (
                    <li
                        key={i}
                        className="flex items-center justify-center rounded-lg bg-muted text-sm font-bold text-gray-600 dark:text-gray-400"
                    >
                        {i + 1}
                    </li>
                ))}
            </ul>
        </ScrollArea>
    ),
} satisfies Story