import { Button, MenuLabel } from '../../../packages/primitives'
import type { Meta, StoryObj } from '@storybook/react'

const meta = {
    title: 'Examples/Layout',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    render: () => (
        <div className="flex rounded-lg bg-background">
            <nav className="bg-muted p-2 rounded-lg w-[200px]">
                <ul className="flex flex-col gap-px [&>li]:w-full [&_button]:w-full">
                    <li><Button left>Home</Button></li>
                    <li><Button left>About</Button></li>
                    <li><Button left>Contact</Button></li>
                    <li><MenuLabel>Settings</MenuLabel></li>
                    <li><Button left>Help</Button></li>
                    <li><Button left>Logout</Button></li>
                </ul>
            </nav>
            <main className="flex-1 p-4 rounded-lg">
                <h1 className="text-2xl font-bold">Main content</h1>
            </main>
            <aside className="bg-muted p-2 rounded-lg w-[200px]">
                <ul className="flex flex-col gap-px [&>li]:w-full [&_button]:w-full">
                    <li><MenuLabel>Sidenav</MenuLabel></li>
                    <li><Button left>Help</Button></li>
                    <li><Button left>Settings</Button></li>
                    <li><Button left>Contact</Button></li>
                </ul>
            </aside>
        </div>
    ),
} satisfies Story

