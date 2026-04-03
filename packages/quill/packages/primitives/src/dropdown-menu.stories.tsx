import type { Meta, StoryObj } from '@storybook/react-vite'
import { IconCopy, IconExpand, IconFolder, IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import { useState } from 'react'

import { Button } from './button'
import {
    DropdownMenu,
    DropdownMenuGroup,
    DropdownMenuContent,
    DropdownMenuTrigger,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioItem,
    DropdownMenuRadioGroup,
} from './dropdown-menu'
import { Kbd } from './kbd'

const meta = {
    title: 'Primitives/DropdownMenu',
    component: DropdownMenu,
    tags: ['autodocs'],
} satisfies Meta<typeof DropdownMenu>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [subOpen, setSubOpen] = useState(true)
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>Click me</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuGroup>
                        <DropdownMenuItem>
                            <IconCopy />
                            Copy
                            <Kbd>⌘C</Kbd>
                        </DropdownMenuItem>
                        <DropdownMenuItem>
                            <IconPencil />
                            Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive">
                            <IconTrash />
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuSub open={subOpen} onOpenChange={setSubOpen}>
                        <DropdownMenuSubTrigger>
                            <IconEllipsis />
                            More
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuItem>
                                <IconFolder />
                                Open in folder
                                <Kbd>⌘O</Kbd>
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                                <IconExpand />
                                Expand
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

export const Checkboxes: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [checkedOne, setCheckedOne] = useState(true)
        const [checkedTwo, setCheckedTwo] = useState(false)
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>Click me</DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto">
                    <DropdownMenuGroup>
                        <DropdownMenuCheckboxItem checked={checkedOne} onCheckedChange={setCheckedOne}>
                            Checkbox Item 1
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem checked={checkedTwo} onCheckedChange={setCheckedTwo}>
                            Checkbox Item 2
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuCheckboxItem disabled>
                            Checkbox Item 2
                        </DropdownMenuCheckboxItem>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

export const Radios: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [radioValue, setRadioValue] = useState('radioOne')
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>Click me</DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto">
                    <DropdownMenuGroup>
                        <DropdownMenuRadioGroup value={radioValue} onValueChange={setRadioValue}>
                            <DropdownMenuRadioItem value="radioOne">Radio Item 1</DropdownMenuRadioItem>
                            <DropdownMenuRadioItem value="radioTwo">Radio Item 2</DropdownMenuRadioItem>
                            <DropdownMenuRadioItem value="radioThree" disabled>Radio Item 3</DropdownMenuRadioItem>
                        </DropdownMenuRadioGroup>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story
