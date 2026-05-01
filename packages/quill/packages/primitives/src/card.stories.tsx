import type { Meta, StoryObj } from '@storybook/react'
import { MoreVertical, UserIcon } from 'lucide-react'

import { Button } from './button'
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './card'
import { Field } from './field'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from './item'

const meta = {
    title: 'Primitives/Card',
    component: Card,
    tags: ['autodocs'],
} satisfies Meta<typeof Card>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <Card className="max-w-sm">
            <CardHeader>
                <CardTitle>Card Title</CardTitle>
                <CardDescription>Card Description</CardDescription>
            </CardHeader>
            <CardContent>
                <p>Card Content</p>
            </CardContent>
            <CardFooter className="flex-col gap-2">
                <Button type="submit" variant="primary" className="w-full">
                    Login
                </Button>
                <Button variant="outline" className="w-full">
                    Cancel
                </Button>
            </CardFooter>
        </Card>
    ),
} satisfies Story

export const Sizes: Story = {
    render: () => (
        <div className="flex flex-col gap-4 max-w-sm">
            <Card size='sm'>
                <CardHeader>
                    <CardTitle>Small size</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button size="icon"><MoreVertical /></Button>
                    </CardAction>
                </CardHeader>
                <CardFooter className="flex-col gap-2">
                    <Button type="submit" variant="primary" className="w-full">
                        Login
                    </Button>
                    <Button variant="outline" className="w-full">
                        Cancel
                    </Button>
                </CardFooter>
            </Card>
            <Card size='sm'>
                <CardHeader>
                    <CardTitle>Small size</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button size="icon"><MoreVertical /></Button>
                    </CardAction>
                </CardHeader>
                <CardContent>
                    <p>Card Content</p>
                </CardContent>
                <CardFooter className="flex-col gap-2">
                    <Button type="submit" variant="primary" className="w-full">
                        Login
                    </Button>
                    <Button variant="outline" className="w-full">
                        Cancel
                    </Button>
                </CardFooter>
            </Card>
            <Card>
                <CardHeader>
                    <CardTitle>Default size</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button size="icon"><MoreVertical /></Button>
                    </CardAction>
                </CardHeader>
                <CardFooter className="flex-col gap-2">
                    <Button type="submit" variant="primary" className="w-full">
                        Login
                    </Button>
                    <Button variant="outline" className="w-full">
                        Cancel
                    </Button>
                </CardFooter>
            </Card>
            <Card>
                <CardHeader>
                    <CardTitle>Default size</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button size="icon"><MoreVertical /></Button>
                    </CardAction>
                </CardHeader>
                <CardContent>
                    <p>Card Content</p>
                </CardContent>
                <CardFooter className="flex-col gap-2">
                    <Button type="submit" variant="primary" className="w-full">
                        Login
                    </Button>
                    <Button variant="outline" className="w-full">
                        Cancel
                    </Button>
                </CardFooter>
            </Card>
        </div>
    ),
} satisfies Story

export const NoContent: Story = {
    render: () => (
        <Card className="max-w-sm">
            <CardHeader>
                <CardTitle>Card Title</CardTitle>
                <CardDescription>Card Description</CardDescription>
            </CardHeader>
            <CardFooter className="flex-col gap-2">
                <Button type="submit" variant="primary" className="w-full">
                    Login
                </Button>
                <Button variant="outline" className="w-full">
                    Cancel
                </Button>
            </CardFooter>
        </Card>
    ),
} satisfies Story

export const WithActions: Story = {
    render: () => (
        <Card className="max-w-sm">
            <CardHeader>
                <CardTitle>Card Title</CardTitle>
                <CardDescription>Card Description</CardDescription>
                <CardAction>
                    <Button variant="outline">Button 1</Button>
                </CardAction>
            </CardHeader>
            <CardContent>
                <p>Card Content</p>
            </CardContent>
            <CardFooter className="flex-col gap-2">
                <Button type="submit" variant="primary" className="w-full">
                    Login
                </Button>
                <Button variant="outline" className="w-full">
                    Cancel
                </Button>
            </CardFooter>
        </Card>
    ),
} satisfies Story

export const CardWithItems: Story = {
    render: () => (
        <Card>
            <CardHeader>
                <CardTitle>Team members</CardTitle>
            </CardHeader>
            <CardContent>
                <Field>
                    <ItemGroup combined>
                        <Item
                            variant="pressable"
                            render={
                                // eslint-disable-next-line react/forbid-elements
                                <a href="#">
                                    <ItemMedia variant="icon">
                                        <UserIcon />
                                    </ItemMedia>
                                    <ItemContent>
                                        <ItemTitle>Alice</ItemTitle>
                                        <ItemDescription>Admin</ItemDescription>
                                    </ItemContent>
                                </a>
                            }
                        />
                        <Item
                            variant="pressable"
                            render={
                                // eslint-disable-next-line react/forbid-elements
                                <a href="#">
                                    <ItemMedia variant="icon">
                                        <UserIcon />
                                    </ItemMedia>
                                    <ItemContent>
                                        <ItemTitle>Bob</ItemTitle>
                                        <ItemDescription>Member</ItemDescription>
                                    </ItemContent>
                                </a>
                            }
                        />
                    </ItemGroup>
                </Field>
            </CardContent>
        </Card>
    ),
} satisfies Story
