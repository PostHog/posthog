import type { Meta, StoryObj } from '@storybook/react-vite'

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
