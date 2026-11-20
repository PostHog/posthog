import type { Meta, StoryObj } from '@storybook/react'
import { Copy, ExpandIcon, Folder, MoreVertical, Pencil, TrashIcon } from 'lucide-react'
import * as React from 'react'
import { useState } from 'react'

import { Button } from './button'
import {
    DropdownMenu,
    DropdownMenuGroup,
    DropdownMenuContent,
    DropdownMenuEmpty,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuList,
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

function FilterableMenu({
    trigger,
    placeholder,
    searchLabel = placeholder,
    emptyText,
    modal,
    autoFocus,
    children,
}: {
    trigger: React.ReactNode
    placeholder: string
    searchLabel?: string
    emptyText: string
    modal?: boolean
    autoFocus?: boolean
    children: React.ReactNode
}): React.ReactElement {
    const [open, setOpen] = useState(true)
    return (
        <DropdownMenuFilterProvider autoHighlight>
            <DropdownMenu modal={modal} open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>{trigger}</DropdownMenuTrigger>
                <DropdownMenuContent className="w-64" flush>
                    <DropdownMenuInput autoFocus={autoFocus} placeholder={placeholder} aria-label={searchLabel} />
                    <DropdownMenuEmpty>{emptyText}</DropdownMenuEmpty>
                    <DropdownMenuList>{children}</DropdownMenuList>
                </DropdownMenuContent>
            </DropdownMenu>
        </DropdownMenuFilterProvider>
    )
}

export const Filterable: Story = {
    render: () => (
        <FilterableMenu trigger="Click me" placeholder="Search projects" emptyText="No project matches" autoFocus>
            <DropdownMenuItem>Analytics</DropdownMenuItem>
            <DropdownMenuItem>Billing</DropdownMenuItem>
            <DropdownMenuItem>Marketing site</DropdownMenuItem>
            <DropdownMenuItem>Onboarding</DropdownMenuItem>
        </FilterableMenu>
    ),
} satisfies Story

export const DescriptionsAndDisabledReasons: Story = {
    render: () => (
        <DropdownMenu defaultOpen>
            <DropdownMenuTrigger render={<Button variant="primary" size="icon" aria-label="New" tooltip="New" />}>
                <MoreVertical />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuItem description="Start from an empty folder">
                    <Folder />
                    New folder
                </DropdownMenuItem>
                <DropdownMenuItem description="Make an exact copy, including its settings">
                    <Copy />
                    Duplicate
                </DropdownMenuItem>
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger description="Rename, move or change who can see it">
                        <Pencil />
                        Edit
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                        <DropdownMenuItem>Rename</DropdownMenuItem>
                        <DropdownMenuItem>Move</DropdownMenuItem>
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" disabledReason="Only owners can delete this folder">
                    <TrashIcon />
                    Delete
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    ),
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
            setSelected((prev) => (checked ? [...prev, value] : prev.filter((v) => v !== value)))
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
            setSelected((prev) => (checked ? [...prev, value] : prev.filter((v) => v !== value)))
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
                                    {state === 'some' && `Select remaining (${FRAMEWORKS.length - selected.length})`}
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
        const { state, toggle: toggleAll } = useDropdownMenuSelectAll(FRAMEWORKS, selected, (next) =>
            setSelected([...next])
        )

        const toggle = (value: string, checked: boolean): void => {
            setSelected((prev) => (checked ? [...prev, value] : prev.filter((v) => v !== value)))
        }

        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>Frameworks</DropdownMenuTrigger>
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
    'Pacific/Midway',
    'Pacific/Honolulu',
    'America/Anchorage',
    'America/Los_Angeles',
    'America/Denver',
    'America/Phoenix',
    'America/Chicago',
    'America/Mexico_City',
    'America/New_York',
    'America/Toronto',
    'America/Halifax',
    'America/Sao_Paulo',
    'Atlantic/Azores',
    'Europe/London',
    'Europe/Dublin',
    'Europe/Lisbon',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Europe/Rome',
    'Europe/Athens',
    'Europe/Helsinki',
    'Africa/Cairo',
    'Europe/Moscow',
    'Asia/Dubai',
    'Asia/Karachi',
    'Asia/Kolkata',
    'Asia/Bangkok',
    'Asia/Singapore',
    'Asia/Hong_Kong',
    'Asia/Shanghai',
    'Asia/Tokyo',
    'Asia/Seoul',
    'Australia/Perth',
    'Australia/Sydney',
    'Pacific/Auckland',
] as const

export const Overflow: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [timezone, setTimezone] = useState<string | undefined>(undefined)
        return (
            <DropdownMenu open={open} onOpenChange={setOpen}>
                <DropdownMenuTrigger render={<Button variant="outline" size="sm" />}>
                    {timezone ?? 'Pick a timezone'}
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-auto min-w-56">
                    {TIMEZONES.map((tz) => (
                        <DropdownMenuItem key={tz} onClick={() => setTimezone(tz)}>
                            {tz}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
        )
    },
} satisfies Story

export const OverflowAndFiltering: Story = {
    render: () => {
        const [timezone, setTimezone] = useState<string | undefined>(undefined)
        const [timezones, setTimezones] = useState<string[]>([])
        return (
            <div className="flex gap-4">
                <div className="w-64">
                    <FilterableMenu
                        trigger={timezone ?? 'Pick a timezone'}
                        placeholder="Search timezones"
                        emptyText="No timezone matches"
                        modal={false}
                    >
                        <DropdownMenuRadioGroup value={timezone} onValueChange={setTimezone}>
                            {TIMEZONES.map((tz) => (
                                <DropdownMenuRadioItem key={tz} value={tz}>
                                    {tz}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </FilterableMenu>
                </div>
                <div className="w-64">
                    <FilterableMenu
                        trigger={timezones.length > 0 ? `${timezones.length} timezones` : 'Pick timezones'}
                        placeholder="Search timezones"
                        searchLabel="Search several timezones"
                        emptyText="No timezone matches"
                        modal={false}
                    >
                        {TIMEZONES.map((tz) => (
                            <DropdownMenuCheckboxItem
                                key={tz}
                                checked={timezones.includes(tz)}
                                closeOnClick={false}
                                onCheckedChange={(checked) =>
                                    setTimezones((current) =>
                                        checked ? [...current, tz] : current.filter((item) => item !== tz)
                                    )
                                }
                            >
                                {tz}
                            </DropdownMenuCheckboxItem>
                        ))}
                    </FilterableMenu>
                </div>
            </div>
        )
    },
} satisfies Story
