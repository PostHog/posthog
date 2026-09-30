import type { Meta, StoryObj } from '@storybook/react'
import { BookIcon, EllipsisIcon, FolderIcon, HashIcon, HomeIcon, PlusIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import { Dot } from './dot'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from './dropdown-menu'
import { MenuLabel } from './menu-label'
import {
    NavItem,
    NavItemAction,
    NavItemButton,
    NavItemContent,
    NavItemDescription,
    NavItemLabel,
    NavItemMeta,
} from './nav-item'
import { Tooltip, TooltipContent, TooltipTrigger } from './tooltip'

const meta: Meta<typeof NavItem> = {
    title: 'Primitives/NavItem',
    component: NavItem,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

const SPACES = ['growth', 'billing', 'onboarding-experiments-with-a-long-name']

export const Default = {
    render: () => {
        const [current, setCurrent] = useState(SPACES[0])
        return (
            <nav aria-label="Spaces" className="flex w-60 flex-col gap-px">
                <MenuLabel>Spaces</MenuLabel>
                {SPACES.map((space) => (
                    <NavItem key={space}>
                        <NavItemButton current={current === space} onClick={() => setCurrent(space)}>
                            <HashIcon />
                            <NavItemLabel>{space}</NavItemLabel>
                        </NavItemButton>
                    </NavItem>
                ))}
            </nav>
        )
    },
} satisfies Story

export const WithMetaAndAction = {
    render: () => (
        <nav aria-label="Recent" className="flex w-60 flex-col gap-px">
            <MenuLabel>Recent</MenuLabel>
            {[
                {
                    title: 'Fix the flaky checkout test',
                    time: '2m',
                    status: 'warning' as const,
                },
                {
                    title: 'Why did signups spike on Monday?',
                    time: '1h',
                    status: 'success' as const,
                },
                {
                    title: 'Add a retry to the billing webhook',
                    time: '3d',
                    status: 'destructive' as const,
                },
            ].map((session, index) => (
                <NavItem key={session.title}>
                    <NavItemButton current={index === 0}>
                        <Dot variant={session.status} />
                        <NavItemLabel>{session.title}</NavItemLabel>
                        <NavItemMeta>{session.time}</NavItemMeta>
                    </NavItemButton>
                    <NavItemAction>
                        <DropdownMenu>
                            <Tooltip>
                                <TooltipTrigger
                                    delay={0}
                                    render={
                                        <DropdownMenuTrigger render={<Button size="icon-xs" aria-label="More" />} />
                                    }
                                >
                                    <EllipsisIcon />
                                </TooltipTrigger>
                                <TooltipContent>More</TooltipContent>
                            </Tooltip>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem>Rename</DropdownMenuItem>
                                <DropdownMenuItem>Archive</DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </NavItemAction>
                </NavItem>
            ))}
        </nav>
    ),
} satisfies Story

export const WithActionOnly = {
    render: () => (
        <nav aria-label="Library" className="flex w-60 flex-col gap-px">
            <NavItem>
                <NavItemButton current>
                    <FolderIcon />
                    <NavItemLabel>All objects</NavItemLabel>
                </NavItemButton>
            </NavItem>
            {['Dashboards', 'Insights', 'Notebooks'].map((type) => (
                <NavItem key={type}>
                    <NavItemButton>
                        <BookIcon />
                        <NavItemLabel>{type}</NavItemLabel>
                    </NavItemButton>
                    <NavItemAction>
                        <Tooltip>
                            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={`New ${type}`} />}>
                                <PlusIcon />
                            </TooltipTrigger>
                            <TooltipContent>{`New ${type}`}</TooltipContent>
                        </Tooltip>
                    </NavItemAction>
                </NavItem>
            ))}
        </nav>
    ),
} satisfies Story

export const AsLink = {
    render: () => (
        <nav aria-label="Main" className="flex w-60 flex-col gap-px">
            <NavItem>
                <NavItemButton current render={<a href="#home" />}>
                    <HomeIcon />
                    <NavItemLabel>Home</NavItemLabel>
                </NavItemButton>
            </NavItem>
        </nav>
    ),
} satisfies Story

export const TwoLine = {
    render: () => (
        <nav aria-label="Reports" className="flex w-60 flex-col gap-px">
            {[
                { title: 'Signup form rejects plus-addressed emails', description: 'Error tracking · 2h' },
                { title: 'LLM costs doubled for the summarize tool', description: 'LLM analytics · 1d' },
            ].map((report, index) => (
                <NavItem key={report.title}>
                    <NavItemButton current={index === 0}>
                        <HomeIcon />
                        <NavItemContent>
                            <NavItemLabel>{report.title}</NavItemLabel>
                            <NavItemDescription>{report.description}</NavItemDescription>
                        </NavItemContent>
                    </NavItemButton>
                </NavItem>
            ))}
        </nav>
    ),
} satisfies Story
