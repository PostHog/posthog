import type { Meta, StoryObj } from '@storybook/react'

import { Dot } from './dot'
import { Button } from './button'

const meta = {
    title: 'Primitives/Dot',
    component: Dot,
    tags: ['autodocs'],
    argTypes: {
        variant: {
            control: 'select',
            options: ['default', 'secondary', 'destructive', 'outline', 'ghost'],
        },
    },
} satisfies Meta<typeof Dot>

export default meta
type Story = StoryObj<typeof meta>

export const Default = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
                <Dot variant="default"/>
                <Dot variant="info"/>
                <Dot variant="destructive"/>
                <Dot variant="warning"/>
                <Dot variant="success"/>
            </div>
        </div>
    ),
} satisfies Story

export const Pulse = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
                <Dot variant="default" pulse/>
                <Dot variant="info" pulse/>
                <Dot variant="destructive" pulse/>
                <Dot variant="warning" pulse/>
                <Dot variant="success" pulse/>
            </div>
        </div>
    ),
} satisfies Story

export const InButton = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
                <Button variant="outline">
                    <Dot variant="default"/>
                    Default
                </Button>
                <Button variant="outline">
                    <Dot variant="info"/>
                    Info
                </Button>
                <Button variant="outline">
                    <Dot variant="destructive"/>
                    Destructive
                </Button>
                <Button variant="outline">
                    <Dot variant="warning"/>
                    Warning
                </Button>
                <Button variant="outline">
                    <Dot variant="success"/>
                    Success
                </Button>
            </div>
            <div className="flex flex-wrap gap-2">
                <Button variant="outline">
                    <Dot variant="default" pulse/>
                    Default
                </Button>
                <Button variant="outline">
                    <Dot variant="info" pulse/>
                    Info
                </Button>
                <Button variant="outline">
                    <Dot variant="destructive" pulse/>
                    Destructive
                </Button>
                <Button variant="outline">
                    <Dot variant="warning" pulse/>
                    Warning
                </Button>
                <Button variant="outline">
                    <Dot variant="success" pulse/>
                    Success
                </Button>
            </div>
        </div>
    ),
} satisfies Story
