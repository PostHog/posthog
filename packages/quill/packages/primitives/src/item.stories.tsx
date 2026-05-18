import type { Meta, StoryObj } from '@storybook/react'
import { BadgeCheckIcon, ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from './combobox'
import {
    DropdownMenu,
    DropdownMenuGroup,
    DropdownMenuContent,
    DropdownMenuTrigger,
    DropdownMenuItem,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSelectAll,
    DropdownMenuSeparator,
} from './dropdown-menu'
import {
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    ItemActions,
    ItemMedia,
    ItemGroup,
    ItemCheckbox,
    ItemRadio,
    ItemMenuItem,
} from './item'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from './select'

const meta = {
    title: 'Primitives/Item',
    component: Item,
    tags: ['autodocs'],
} satisfies Meta<typeof Item>

export default meta
type Story = StoryObj<typeof meta>

const people = [
    { username: 'John Doe', email: 'john.doe@example.com' },
    { username: 'Jane Doe', email: 'jane.doe@example.com' },
    { username: 'Jim Doe', email: 'jim.doe@example.com' },
    { username: 'Jill Doe', email: 'jill.doe@example.com' },
]

export const Default: Story = {
    render: () => (
        <Item variant="outline">
            <ItemContent>
                <ItemTitle>Basic Item</ItemTitle>
                <ItemDescription>A simple item with title and description.</ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button variant="outline">Action</Button>
            </ItemActions>
        </Item>
    ),
} satisfies Story

export const Pressable: Story = {
    render: () => (
        <Item
            variant="pressable"
            size="sm"
            render={
                // eslint-disable-next-line react/forbid-elements
                <a href="#">
                    <ItemMedia variant="icon">
                        <BadgeCheckIcon className="size-5" />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>Your profile has been verified.</ItemTitle>
                        <ItemDescription>A simple item with title and description.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <ChevronRightIcon className="size-4" />
                    </ItemActions>
                </a>
            }
        />
    ),
} satisfies Story

export const Group: Story = {
    render: () => (
        <ItemGroup>
            <ItemGroup>
                <Item variant="outline">
                    <ItemContent>
                        <ItemTitle>Basic Item</ItemTitle>
                        <ItemDescription>A simple item with title and description.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline">Action</Button>
                    </ItemActions>
                </Item>
                <Item variant="outline">
                    <ItemContent>
                        <ItemTitle>Basic Item</ItemTitle>
                        <ItemDescription>A simple item with title and description.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline">Action</Button>
                    </ItemActions>
                </Item>
            </ItemGroup>
            <Item variant="outline">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>A simple item with title and description.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline">Action</Button>
                </ItemActions>
            </Item>
        </ItemGroup>
    ),
} satisfies Story

export const GroupList: Story = {
    render: () => (
        <ItemGroup>
            <Item
                variant="pressable"
                size="xs"
                render={
                    // eslint-disable-next-line react/forbid-elements
                    <a href="#">
                        <ItemContent>
                            <ItemTitle>List link item</ItemTitle>
                        </ItemContent>
                    </a>
                }
            />
            <Item
                variant="pressable"
                size="xs"
                render={
                    // eslint-disable-next-line react/forbid-elements
                    <a href="#">
                        <ItemContent>
                            <ItemTitle>List link item</ItemTitle>
                        </ItemContent>
                    </a>
                }
            />
            <Item
                variant="pressable"
                size="xs"
                render={
                    // eslint-disable-next-line react/forbid-elements
                    <a href="#">
                        <ItemContent>
                            <ItemTitle>List link item</ItemTitle>
                        </ItemContent>
                    </a>
                }
            />
        </ItemGroup>
    ),
} satisfies Story

export const DropdownInItem: Story = {
    render: () => {
        const [open, setOpen] = useState(true)

        return (
            <Item variant="outline" className="max-w-sm">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>A simple item with title and description.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <DropdownMenu open={open} onOpenChange={setOpen}>
                        <DropdownMenuTrigger render={(props) => <Button variant="outline" {...props} />}>
                            Dropdown
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="w-auto" align="end">
                            <DropdownMenuGroup>
                                {people.map((person) => (
                                    <DropdownMenuItem
                                        key={person.username}
                                        render={
                                            <ItemMenuItem size="xs" className="w-full">
                                                <ItemContent variant="menuItem">
                                                    <ItemTitle>{person.username}</ItemTitle>
                                                    <ItemDescription className="leading-none">
                                                        {person.email}
                                                    </ItemDescription>
                                                </ItemContent>
                                            </ItemMenuItem>
                                        }
                                    />
                                ))}
                            </DropdownMenuGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </ItemActions>
            </Item>
        )
    },
} satisfies Story

export const DropdownCheckboxesInItem: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [checked, setChecked] = useState<Record<string, boolean>>({
            'John Doe': true,
            'Jane Doe': false,
            'Jim Doe': false,
            'Jill Doe': false,
        })

        const handleCheckedChange = (username: string): void => {
            setChecked((prev) => ({ ...prev, [username]: !prev[username] }))
        }
        return (
            <Item variant="outline" className="max-w-sm">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>A simple item with title and description.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <DropdownMenu open={open} onOpenChange={setOpen}>
                        <DropdownMenuTrigger render={(props) => <Button variant="outline" {...props} />}>
                            Dropdown Checkboxes
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="w-auto" align="end">
                            <DropdownMenuGroup>
                                {people.map((person) => (
                                    <DropdownMenuCheckboxItem
                                        key={person.username}
                                        checked={checked[person.username]}
                                        onCheckedChange={() => handleCheckedChange(person.username)}
                                        render={(props) => (
                                            <ItemCheckbox size="xs" {...props}>
                                                <ItemContent variant="menuItem">
                                                    <ItemTitle>{person.username}</ItemTitle>
                                                    <ItemDescription className="leading-none">
                                                        {person.email}
                                                    </ItemDescription>
                                                </ItemContent>
                                            </ItemCheckbox>
                                        )}
                                    />
                                ))}
                            </DropdownMenuGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </ItemActions>
            </Item>
        )
    },
} satisfies Story

export const DropdownCheckboxesInItemWithSelectAll: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [selected, setSelected] = useState<string[]>([people[0].username])

        const usernames = people.map((p) => p.username)

        const toggle = (username: string, checked: boolean): void => {
            setSelected((prev) =>
                checked ? [...prev, username] : prev.filter((u) => u !== username)
            )
        }

        return (
            <Item variant="outline" className="max-w-sm">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>
                        Multi-select with a headless select-all action above the list.
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <DropdownMenu open={open} onOpenChange={setOpen}>
                        <DropdownMenuTrigger render={(props) => <Button variant="outline" {...props} />}>
                            {selected.length} / {people.length} selected
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="w-auto" align="end">
                            <DropdownMenuGroup>
                                <DropdownMenuSelectAll
                                    values={usernames}
                                    selected={selected}
                                    onChange={(next) => setSelected([...next])}
                                />
                                <DropdownMenuSeparator />
                                {people.map((person) => (
                                    <DropdownMenuCheckboxItem
                                        key={person.username}
                                        checked={selected.includes(person.username)}
                                        onCheckedChange={(checked) => toggle(person.username, !!checked)}
                                        closeOnClick={false}
                                        render={(props) => (
                                            <ItemCheckbox size="xs" {...props}>
                                                <ItemContent variant="menuItem">
                                                    <ItemTitle>{person.username}</ItemTitle>
                                                    <ItemDescription className="leading-none">
                                                        {person.email}
                                                    </ItemDescription>
                                                </ItemContent>
                                            </ItemCheckbox>
                                        )}
                                    />
                                ))}
                            </DropdownMenuGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </ItemActions>
            </Item>
        )
    },
} satisfies Story

export const DropdownRadiosInItem: Story = {
    render: () => {
        const [open, setOpen] = useState(true)
        const [radioValue, setRadioValue] = useState('John Doe')

        return (
            <Item variant="outline" className="max-w-sm">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>A simple item with title and description.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <DropdownMenu open={open} onOpenChange={setOpen}>
                        <DropdownMenuTrigger render={(props) => <Button variant="outline" {...props} />}>
                            Dropdown Radios
                        </DropdownMenuTrigger>
                        <DropdownMenuContent className="w-auto" align="end">
                            <DropdownMenuRadioGroup value={radioValue} onValueChange={setRadioValue}>
                                {people.map((person) => (
                                    <DropdownMenuRadioItem
                                        key={person.username}
                                        value={person.username}
                                        render={(props) => (
                                            <ItemRadio size="xs" {...props}>
                                                <ItemContent variant="menuItem">
                                                    <ItemTitle>{person.username}</ItemTitle>
                                                    <ItemDescription className="leading-none">
                                                        {person.email}
                                                    </ItemDescription>
                                                </ItemContent>
                                            </ItemRadio>
                                        )}
                                    />
                                ))}
                            </DropdownMenuRadioGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </ItemActions>
            </Item>
        )
    },
} satisfies Story

export const SelectInItem: Story = {
    render: () => {
        const [open, setOpen] = useState(true)

        return (
            <Item variant="outline" className="max-w-sm mt-32">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>A simple item with title and description.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Select
                        open={open}
                        onOpenChange={setOpen}
                        defaultValue={people[0]}
                        itemToStringLabel={(person: (typeof people)[number]) => person.username}
                        itemToStringValue={(person: (typeof people)[number]) => person.username}
                    >
                        <SelectTrigger render={(props) => <Button variant="outline" {...props} className="h-min" />}>
                            <SelectValue>
                                {(person: (typeof people)[number]) => (
                                    <ItemContent variant="menuItem">
                                        <ItemTitle>{person.username}</ItemTitle>
                                        <ItemDescription className="leading-none">{person.email}</ItemDescription>
                                    </ItemContent>
                                )}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent className="min-w-(--anchor-width)" align="end" sideOffset={8}>
                            <SelectGroup>
                                {people.map((person) => (
                                    <SelectItem key={person.username} value={person} className="py-0">
                                        <ItemContent variant="menuItem">
                                            <ItemTitle>{person.username}</ItemTitle>
                                            <ItemDescription className="leading-none">{person.email}</ItemDescription>
                                        </ItemContent>
                                    </SelectItem>
                                ))}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </ItemActions>
            </Item>
        )
    },
} satisfies Story

export const ComboboxInItem: Story = {
    render: () => {
        const [open, setOpen] = useState(true)

        return (
            <Item variant="outline" className="max-w-sm mt-32">
                <ItemContent>
                    <ItemTitle>Basic Item</ItemTitle>
                    <ItemDescription>A simple item with title and description.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Combobox
                        items={people.filter((person) => person.username !== '')}
                        itemToStringLabel={(person: (typeof people)[number]) => person.username}
                        itemToStringValue={(person: (typeof people)[number]) => person.username}
                        open={open}
                        onOpenChange={setOpen}
                    >
                        <ComboboxInput placeholder="Search people..." className="max-w-xs" />
                        <ComboboxContent>
                            <ComboboxEmpty>No people found.</ComboboxEmpty>
                            <ComboboxList>
                                {(person) => (
                                    <ComboboxItem key={person.username} value={person} className="h-auto">
                                        <Item size="xs" className="p-0">
                                            <ItemContent variant="menuItem">
                                                <ItemTitle className="whitespace-nowrap">{person.username}</ItemTitle>
                                                <ItemDescription>{person.email}</ItemDescription>
                                            </ItemContent>
                                        </Item>
                                    </ComboboxItem>
                                )}
                            </ComboboxList>
                        </ComboboxContent>
                    </Combobox>
                </ItemActions>
            </Item>
        )
    },
} satisfies Story
