import type { Meta, StoryObj } from '@storybook/react-vite'
import { IconCheckCircle, IconChevronRight } from '@posthog/icons'
import { useState } from 'react'

import { Button } from './button'
import {
    DropdownMenu,
    DropdownMenuGroup,
    DropdownMenuContent,
    DropdownMenuTrigger,
    DropdownMenuItem,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
} from './dropdown-menu'
import { Item, ItemContent, ItemDescription, ItemTitle, ItemActions, ItemMedia, ItemGroup, ItemCheckbox, ItemRadio, ItemMenuItem } from './item'

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
                        <IconCheckCircle className="size-5" />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>Your profile has been verified.</ItemTitle>
                        <ItemDescription>A simple item with title and description.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <IconChevronRight className="size-4" />
                    </ItemActions>
                </a>
            }
        />
    ),
} satisfies Story

export const Group: Story = {
    render: () => (
        <ItemGroup>
            <ItemGroup combined>
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
        <ItemGroup combined>
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

export const ItemInDropdown: Story = {
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
                                                <ItemContent className="gap-0 py-1 px-1.5">
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

export const ItemCheckboxInDropdown: Story = {
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
                                            <ItemCheckbox size="xs" className="w-full" {...props}>
                                                <ItemContent className="gap-0 py-1 px-1.5">
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

export const ItemRadiosInDropdown: Story = {
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
                                            <ItemRadio size="xs" className="w-full" {...props}>
                                                <ItemContent className="gap-0 py-1 px-1.5">
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
