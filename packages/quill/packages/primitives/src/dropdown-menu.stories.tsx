import type { Meta, StoryObj } from '@storybook/react'
import { Copy, ExpandIcon, Folder, MoreVertical, Pencil, TrashIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import {
    DropdownMenu,
    DropdownMenuGroup,
    DropdownMenuContent,
    DropdownMenuTrigger,
    DropdownMenuItem,
    DropdownMenuSelectAll,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioItem,
    DropdownMenuRadioGroup,
    DropdownMenuLabel,
    useDropdownMenuSelectAll,
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
                            <Copy />
                            Copy
                            <Kbd>⌘C</Kbd>
                        </DropdownMenuItem>
                        <DropdownMenuItem>
                            <Pencil />
                            Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive">
                            <TrashIcon />
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuSub open={subOpen} onOpenChange={setSubOpen}>
                        <DropdownMenuSubTrigger>
                            <MoreVertical />
                            More
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuItem>
                                <Folder />
                                Open in folder
                                <Kbd>⌘O</Kbd>
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                                <ExpandIcon />
                                Expand
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

export const Labels: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [subOpen, setSubOpen] = useState(true)
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>Click me</DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Group label</DropdownMenuLabel>
                        <DropdownMenuItem>
                            <Copy />
                            Copy
                            <Kbd>⌘C</Kbd>
                        </DropdownMenuItem>
                        <DropdownMenuItem>
                            <Pencil />
                            Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive">
                            <TrashIcon />
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuSub open={subOpen} onOpenChange={setSubOpen}>
                        <DropdownMenuSubTrigger>
                            <MoreVertical />
                            More
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            <DropdownMenuItem>
                                <Folder />
                                Open in folder
                                <Kbd>⌘O</Kbd>
                            </DropdownMenuItem>
                            <DropdownMenuItem>
                                <ExpandIcon />
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
        const [checkedTwo, setCheckedTwo] = useState(true)
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
                        <DropdownMenuCheckboxItem disabled>Checkbox Item 2</DropdownMenuCheckboxItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem>
                                <ExpandIcon />
                                Expand
                            </DropdownMenuItem>
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
                            <DropdownMenuRadioItem value="radioThree" disabled>
                                Radio Item 3
                            </DropdownMenuRadioItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem>
                                <ExpandIcon />
                                Expand
                            </DropdownMenuItem>
                        </DropdownMenuRadioGroup>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

const FRAMEWORKS = ['Next.js', 'Remix', 'SvelteKit', 'Nuxt'] as const

export const SelectAll: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [selected, setSelected] = useState<string[]>([])

        const toggle = (value: string, checked: boolean): void => {
            setSelected((prev) =>
                checked ? [...prev, value] : prev.filter((v) => v !== value)
            )
        }

        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    {selected.length} selected
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto min-w-48">
                    <DropdownMenuGroup>
                        <DropdownMenuSelectAll
                            values={FRAMEWORKS}
                            selected={selected}
                            onChange={(next) => setSelected([...next])}
                        />
                        <DropdownMenuSeparator />
                        {FRAMEWORKS.map((value) => (
                            <DropdownMenuCheckboxItem
                                key={value}
                                checked={selected.includes(value)}
                                onCheckedChange={(checked) => toggle(value, !!checked)}
                                closeOnClick={false}
                            >
                                {value}
                            </DropdownMenuCheckboxItem>
                        ))}
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

export const SelectAllWithRenderProp: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [selected, setSelected] = useState<string[]>([FRAMEWORKS[0]])

        const toggle = (value: string, checked: boolean): void => {
            setSelected((prev) =>
                checked ? [...prev, value] : prev.filter((v) => v !== value)
            )
        }

        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    {selected.length} / {FRAMEWORKS.length}
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto min-w-56">
                    <DropdownMenuGroup>
                        <DropdownMenuSelectAll
                            values={FRAMEWORKS}
                            selected={selected}
                            onChange={(next) => setSelected([...next])}
                        >
                            {({ state, toggle: toggleAll }) => (
                                <DropdownMenuItem closeOnClick={false} onClick={toggleAll}>
                                    {state === 'all' && 'Clear selection'}
                                    {state === 'some' &&
                                        `Select remaining (${FRAMEWORKS.length - selected.length})`}
                                    {state === 'none' && 'Select all'}
                                </DropdownMenuItem>
                            )}
                        </DropdownMenuSelectAll>
                        <DropdownMenuSeparator />
                        {FRAMEWORKS.map((value) => (
                            <DropdownMenuCheckboxItem
                                key={value}
                                checked={selected.includes(value)}
                                onCheckedChange={(checked) => toggle(value, !!checked)}
                                closeOnClick={false}
                            >
                                {value}
                            </DropdownMenuCheckboxItem>
                        ))}
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

export const SelectAllWithHook: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [selected, setSelected] = useState<string[]>([])
        const { state, toggle: toggleAll } = useDropdownMenuSelectAll(
            FRAMEWORKS,
            selected,
            (next) => setSelected([...next])
        )

        const toggle = (value: string, checked: boolean): void => {
            setSelected((prev) =>
                checked ? [...prev, value] : prev.filter((v) => v !== value)
            )
        }

        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    Frameworks
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto min-w-56">
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>
                            Frameworks ({selected.length}/{FRAMEWORKS.length})
                        </DropdownMenuLabel>
                        <DropdownMenuItem closeOnClick={false} onClick={toggleAll}>
                            {state === 'all' ? 'Deselect all' : 'Select all'}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        {FRAMEWORKS.map((value) => (
                            <DropdownMenuCheckboxItem
                                key={value}
                                checked={selected.includes(value)}
                                onCheckedChange={(checked) => toggle(value, !!checked)}
                                closeOnClick={false}
                            >
                                {value}
                            </DropdownMenuCheckboxItem>
                        ))}
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

const TIMEZONES = [
    'Pacific/Midway', 'Pacific/Honolulu', 'America/Anchorage', 'America/Los_Angeles',
    'America/Denver', 'America/Phoenix', 'America/Chicago', 'America/Mexico_City',
    'America/New_York', 'America/Toronto', 'America/Halifax', 'America/Sao_Paulo',
    'Atlantic/Azores', 'Europe/London', 'Europe/Dublin', 'Europe/Lisbon',
    'Europe/Paris', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Rome',
    'Europe/Athens', 'Europe/Helsinki', 'Africa/Cairo', 'Europe/Moscow',
    'Asia/Dubai', 'Asia/Karachi', 'Asia/Kolkata', 'Asia/Bangkok',
    'Asia/Singapore', 'Asia/Hong_Kong', 'Asia/Shanghai', 'Asia/Tokyo',
    'Asia/Seoul', 'Australia/Perth', 'Australia/Sydney', 'Pacific/Auckland',
] as const

export const Overflow: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    Pick a timezone
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto min-w-56">
                    <DropdownMenuGroup>
                        {TIMEZONES.map((tz) => (
                            <DropdownMenuItem key={tz}>{tz}</DropdownMenuItem>
                        ))}
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story
