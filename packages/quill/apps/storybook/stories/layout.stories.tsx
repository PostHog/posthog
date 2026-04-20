import { Button, Card, CardContent, CardFooter, CardHeader, CardTitle, MenuLabel } from '../../../packages/primitives'
import type { Meta, StoryObj } from '@storybook/react'

const meta = {
    title: 'Examples/Layout',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <div className="flex rounded-lg bg-background gap-4">
            <nav className="flex flex-col gap-2 p-2 rounded-lg w-[200px]">
                <ul className="bg-muted p-4 flex flex-col gap-px [&>li]:w-full [&_button]:w-full rounded-lg">
                    <li><Button left variant="primary">Primary</Button></li>
                    <li><Button left aria-selected>Selected</Button></li>
                    <li><Button left>Contact</Button></li>
                    <li><MenuLabel>Settings</MenuLabel></li>
                    <li><Button left>Help</Button></li>
                    <li><Button left>Logout</Button></li>
                </ul>
                <ul className="p-4 flex flex-col gap-px [&>li]:w-full [&_button]:w-full rounded-lg">
                    <li><Button left variant="primary">Primary</Button></li>
                    <li><Button left aria-selected>Selected</Button></li>
                    <li><Button left>Contact</Button></li>
                </ul>
            </nav>
            <main className="flex flex-col gap-4 flex-1 rounded-lg p-4">
                <h1 className="text-xl font-bold">Main content</h1>
                <Card size="sm">
                    <CardHeader>
                        <CardTitle>Card Title</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p>Card Content</p>
                    </CardContent>
                    <CardFooter>
                        <Button>Action</Button>
                    </CardFooter>
                </Card>
            </main>
            <aside className="p-2 rounded-lg w-[200px] [--theme-hue:570]">
                <ul className="flex flex-col gap-px [&>li]:w-full [&_button]:w-full bg-muted p-4 rounded-lg">
                    <li><MenuLabel>Sidenav</MenuLabel></li>
                    <li><Button left variant="primary">Help</Button></li>
                    <li><Button left aria-selected>Settings</Button></li>
                    <li><Button left>Contact</Button></li>
                </ul>
            </aside>
        </div>
    ),
} satisfies Story

