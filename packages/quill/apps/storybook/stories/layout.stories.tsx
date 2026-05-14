import React from 'react'
import { Button, Card, CardContent, CardFooter, CardHeader, CardTitle, MenuLabel } from '../../../packages/primitives/src'
import type { Meta, StoryObj } from '@storybook/react'

const meta = {
    title: 'Examples/Layout',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

const Nav = (): React.ReactElement => (
    <nav className="flex flex-col gap-2 p-2 rounded-lg w-[200px]">
        <ul className="bg-muted p-4 flex flex-col gap-px [&>li]:w-full [&_button]:w-full rounded-lg">
            <li><MenuLabel>Menu Label</MenuLabel></li>
            <li className="mb-1"><Button left variant="primary">Primary</Button></li>
            <li><Button left aria-expanded>Expanded</Button></li>
            <li><Button left aria-selected>Selected</Button></li>
            <li><Button left>Default</Button></li>
        </ul>
        <ul className="p-4 flex flex-col gap-px [&>li]:w-full [&_button]:w-full rounded-lg">
            <li><MenuLabel>Menu Label</MenuLabel></li>
            <li><Button left variant="primary">Primary</Button></li>
            <li><Button left aria-expanded>Expanded</Button></li>
            <li><Button left aria-selected>Selected</Button></li>
            <li><Button left>Default</Button></li>
        </ul>
    </nav>
)

const Main = (): React.ReactElement => (
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
)

const Aside = (): React.ReactElement => (
    <aside className="p-2 rounded-lg w-[200px] [--theme-hue:570] [--theme-dark-hue:189]">
        <ul className="flex flex-col gap-px [&>li]:w-full [&_button]:w-full bg-muted p-4 rounded-lg">
            <li><MenuLabel>Menu Label</MenuLabel></li>
            <li><Button left variant="primary">Primary</Button></li>
            <li><Button left aria-expanded>Expanded</Button></li>
            <li><Button left aria-selected>Selected</Button></li>
            <li><Button left>Default</Button></li>
        </ul>
    </aside>
)

export const Default: Story = {
    render: () => (
        <div className="flex rounded-lg bg-background gap-4">
            <Nav />
            <Main />
            <Aside />
        </div>
    ),
} satisfies Story

