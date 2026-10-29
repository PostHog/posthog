import type { Meta, StoryObj } from '@storybook/react'

import { Badge } from './badge'
import { Button } from './button'
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from './card'
import { CardGroup } from './card-group'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from './dropdown-menu'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from './select'
import { Text } from './text'

const meta = {
    title: 'Primitives/Card Group',
    component: CardGroup,
    tags: ['autodocs'],
} satisfies Meta<typeof CardGroup>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <CardGroup className="max-w-sm">
            <Card>
                <CardHeader>
                    <CardTitle>Card Title</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button variant="outline">Button 1</Button>
                    </CardAction>
                </CardHeader>
            </Card>
            <Card>
                <CardHeader>
                    <CardTitle>Card Title</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button variant="outline">Button 1</Button>
                    </CardAction>
                </CardHeader>
            </Card>
        </CardGroup>
    ),
} satisfies Story

export const Small: Story = {
    render: () => (
        <CardGroup className="max-w-sm">
            <Card size="sm">
                <CardHeader>
                    <CardTitle>Card Title</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button variant="outline">Button 1</Button>
                    </CardAction>
                </CardHeader>
            </Card>
            <Card size="sm">
                <CardHeader>
                    <CardTitle>Card Title</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button variant="outline">Button 1</Button>
                    </CardAction>
                </CardHeader>
            </Card>
        </CardGroup>
    ),
} satisfies Story

export const Multiple: Story = {
    render: () => {
        const items = [
            { label: 'select an option', value: null },
            { label: 'Option 1', value: '1' },
            { label: 'Option 2', value: '2' },
            { label: 'Option 3', value: '3' },
        ]
        return (
            <CardGroup className="max-w-sm">
                <CardGroup>
                    <Card>
                        <CardHeader>
                            <CardTitle>Dropdown Menu</CardTitle>
                            <CardDescription>Card Description</CardDescription>
                            <CardAction>
                                <DropdownMenu>
                                    <DropdownMenuTrigger render={(props) => <Button variant="outline" {...props} />}>
                                        Dropdown Menu
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end">
                                        <DropdownMenuGroup>
                                            <DropdownMenuItem>Item 1</DropdownMenuItem>
                                            <DropdownMenuItem>Item 1</DropdownMenuItem>
                                        </DropdownMenuGroup>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </CardAction>
                        </CardHeader>
                    </Card>
                    <Card>
                        <CardHeader>
                            <CardTitle>Select</CardTitle>
                            <CardDescription>Card Description</CardDescription>
                            <CardAction>
                                <Select items={items}>
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent align="end">
                                        <SelectGroup>
                                            {items.map((item) => (
                                                <SelectItem key={item.value} value={item.value}>
                                                    {item.label}
                                                </SelectItem>
                                            ))}
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </CardAction>
                        </CardHeader>
                    </Card>
                </CardGroup>

                <CardGroup>
                    <Card>
                        <CardHeader>
                            <CardTitle>Card Title</CardTitle>
                            <CardDescription>Card Description</CardDescription>
                            <CardAction>
                                <Button variant="outline">Button 1</Button>
                            </CardAction>
                        </CardHeader>
                    </Card>
                    <Card>
                        <CardHeader>
                            <CardTitle>Card Title</CardTitle>
                            <CardDescription>Card Description</CardDescription>
                            <CardAction>
                                <Button variant="outline">Button 1</Button>
                            </CardAction>
                        </CardHeader>
                    </Card>
                </CardGroup>
            </CardGroup>
        )
    },
} satisfies Story

// A list of clickable rows: each Card holds one full-width button or link, so the whole row is the target.
export const ClickableRows: Story = {
    render: () => (
        <CardGroup className="max-w-sm">
            {[
                {
                    title: 'Thanks, that fixed the funnel. One more question about breakdowns',
                    meta: '#1042 · 3 hours ago',
                    status: 'Open',
                },
                {
                    title: 'We are looking into the missing network requests',
                    meta: '#1037 · 2 days ago',
                    status: 'Pending',
                },
                { title: 'Glad that worked. Closing this one out.', meta: '#1001 · 20 days ago', status: 'Resolved' },
            ].map((row) => (
                <Card key={row.meta} size="sm" className="p-0">
                    <button
                        type="button"
                        className="flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2.5 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                    >
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <Text size="sm" render={<span />} className="block truncate">
                                {row.title}
                            </Text>
                            <Text size="xs" variant="muted" render={<span />} className="block truncate">
                                {row.meta}
                            </Text>
                        </span>
                        <Badge className="shrink-0">{row.status}</Badge>
                    </button>
                </Card>
            ))}
        </CardGroup>
    ),
} satisfies Story
