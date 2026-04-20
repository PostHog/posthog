import type { Meta, StoryObj } from '@storybook/react'
import { Copy, ExpandIcon, MoreVertical, Pencil, TrashIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import {
    ContextMenu,
    ContextMenuCheckboxItem,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuRadioGroup,
    ContextMenuRadioItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from './context-menu'

const meta = {
    title: 'Primitives/ContextMenu',
    component: ContextMenu,
    tags: ['autodocs'],
} satisfies Meta<typeof ContextMenu>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <ContextMenu>
            <ContextMenuTrigger render={<Button variant="outline" size="sm" />}>Side-click me</ContextMenuTrigger>
            <ContextMenuContent>
                <ContextMenuGroup>
                    <ContextMenuItem>
                        <Copy />
                        Copy
                    </ContextMenuItem>
                    <ContextMenuItem>
                        <Pencil />
                        Rename
                    </ContextMenuItem>
                    <ContextMenuItem variant="destructive">
                        <TrashIcon />
                        Delete
                    </ContextMenuItem>
                </ContextMenuGroup>
                <ContextMenuSeparator />
                <ContextMenuSub>
                    <ContextMenuSubTrigger>
                        <MoreVertical />
                        More
                    </ContextMenuSubTrigger>
                    <ContextMenuSubContent>
                        <ContextMenuItem>
                            <Copy />
                            Copy
                        </ContextMenuItem>
                    </ContextMenuSubContent>
                </ContextMenuSub>
            </ContextMenuContent>
        </ContextMenu>
    ),
} satisfies Story

export const Checkboxes: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [checkedOne, setCheckedOne] = useState(true)
        const [checkedTwo, setCheckedTwo] = useState(false)
        return (
            <ContextMenu open={open} onOpenChange={setOpen}>
                <ContextMenuTrigger render={<Button variant="outline" size="sm" />}>Side-click me</ContextMenuTrigger>
                <ContextMenuContent className="w-auto">
                    <ContextMenuGroup>
                        <ContextMenuCheckboxItem checked={checkedOne} onCheckedChange={setCheckedOne}>
                            Checkbox Item 1
                        </ContextMenuCheckboxItem>
                        <ContextMenuCheckboxItem checked={checkedTwo} onCheckedChange={setCheckedTwo}>
                            Checkbox Item 2
                        </ContextMenuCheckboxItem>
                        <ContextMenuCheckboxItem disabled>Checkbox Item 2</ContextMenuCheckboxItem>
                        <ContextMenuSeparator />
                        <ContextMenuItem>
                                <ExpandIcon />
                                Expand
                            </ContextMenuItem>
                    </ContextMenuGroup>
                </ContextMenuContent>
            </ContextMenu>
        )
    },
} satisfies Story

export const Radios: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [radioValue, setRadioValue] = useState('radioOne')
        return (
            <ContextMenu open={open} onOpenChange={setOpen}>
                <ContextMenuTrigger render={<Button variant="outline" size="sm" />}>Side-click me</ContextMenuTrigger>
                <ContextMenuContent className="w-auto">
                    <ContextMenuGroup>
                        <ContextMenuRadioGroup value={radioValue} onValueChange={setRadioValue}>
                            <ContextMenuRadioItem value="radioOne">Radio Item 1</ContextMenuRadioItem>
                            <ContextMenuRadioItem value="radioTwo">Radio Item 2</ContextMenuRadioItem>
                            <ContextMenuRadioItem value="radioThree" disabled>
                                Radio Item 3
                            </ContextMenuRadioItem>
                            <ContextMenuSeparator />
                            <ContextMenuItem>
                                <ExpandIcon />
                                Expand
                            </ContextMenuItem>
                        </ContextMenuRadioGroup>
                    </ContextMenuGroup>
                </ContextMenuContent>
            </ContextMenu>
        )
    },
} satisfies Story
