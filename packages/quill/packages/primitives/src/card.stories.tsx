import type { Meta, StoryObj } from '@storybook/react'
import { MoreVertical, UserIcon } from 'lucide-react'

import { Button } from './button'
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './card'
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from './item'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './table'

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
            <Card size="sm">
                <CardHeader>
                    <CardTitle>Small size</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button size="icon">
                            <MoreVertical />
                        </Button>
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
            <Card size="sm">
                <CardHeader>
                    <CardTitle>Small size</CardTitle>
                    <CardDescription>Card Description</CardDescription>
                    <CardAction>
                        <Button size="icon">
                            <MoreVertical />
                        </Button>
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
                        <Button size="icon">
                            <MoreVertical />
                        </Button>
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
                        <Button size="icon">
                            <MoreVertical />
                        </Button>
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

const REVENUE_ROWS = [
    { plan: 'Free', customers: 1204, revenue: '$0' },
    { plan: 'Pay-as-you-go', customers: 312, revenue: '$18,420' },
    { plan: 'Enterprise', customers: 14, revenue: '$96,000' },
]

// `flush` lets a full-bleed child (here a Table) run to the card's rounded edges: the card
// drops its section gap + bottom padding and the CardContent its inline padding, while the
// header keeps its own. The Table's `size` matches the Card's so edge columns line up with
// the header title.
export const Flush: Story = {
    render: () => (
        <div className="flex max-w-md flex-col gap-4">
            {(['default', 'sm'] as const).map((size) => (
                <Card key={size} size={size} flush>
                    <CardHeader>
                        <CardTitle>Revenue</CardTitle>
                        <CardDescription>Last 30 days · size="{size}"</CardDescription>
                    </CardHeader>
                    <CardContent>
                        <Table size={size} fullWidth>
                            <TableHeader>
                                <TableRow>
                                    <TableHead expand>Plan</TableHead>
                                    <TableHead align="right">Customers</TableHead>
                                    <TableHead align="right">Revenue</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {REVENUE_ROWS.map((row) => (
                                    <TableRow key={row.plan}>
                                        <TableCell expand>{row.plan}</TableCell>
                                        <TableCell align="right">{row.customers.toLocaleString()}</TableCell>
                                        <TableCell align="right">{row.revenue}</TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </CardContent>
                </Card>
            ))}
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
            <CardContent className="py-0">
                <ItemGroup>
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
            </CardContent>
        </Card>
    ),
} satisfies Story
