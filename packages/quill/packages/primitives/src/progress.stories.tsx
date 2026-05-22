import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { Progress, ProgressIndicator, ProgressLabel, ProgressTrack, ProgressValue } from './progress'

const meta = {
    title: 'Primitives/Progress',
    component: Progress,
    tags: ['autodocs'],
    argTypes: {
        variant: {
            control: 'select',
            options: ['default', 'info', 'success', 'warning', 'destructive'],
        },
        value: {
            control: { type: 'range', min: 0, max: 100, step: 1 },
        },
    },
} satisfies Meta<typeof Progress>

export default meta
type Story = StoryObj<typeof meta>

export const Default = {
    args: {
        value: 56,
        variant: 'default',
    },
    render: (args) => (
        <Progress {...args} className="w-full max-w-sm">
            <ProgressLabel>Upload progress</ProgressLabel>
            <ProgressValue />
        </Progress>
    ),
} satisfies Story

export const Variants = {
    render: () => (
        <div className="flex w-full max-w-sm flex-col gap-4">
            <Progress value={68} variant="default">
                <ProgressLabel>Default</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Progress value={42} variant="info">
                <ProgressLabel>Info</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Progress value={92} variant="success">
                <ProgressLabel>Success</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Progress value={31} variant="warning">
                <ProgressLabel>Warning</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Progress value={12} variant="destructive">
                <ProgressLabel>Destructive</ProgressLabel>
                <ProgressValue />
            </Progress>
        </div>
    ),
} satisfies Story

export const NoLabel = {
    render: () => (
        <div className="flex w-full max-w-sm flex-col gap-3">
            <Progress value={68} variant="default" />
            <Progress value={42} variant="info" />
            <Progress value={92} variant="success" />
            <Progress value={31} variant="warning" />
            <Progress value={12} variant="destructive" />
        </div>
    ),
} satisfies Story

export const ValueBoundary = {
    render: () => (
        <div className="flex w-full max-w-sm flex-col gap-4">
            <Progress value={0} variant="default">
                <ProgressLabel>Empty (0%)</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Progress value={100} variant="success">
                <ProgressLabel>Complete (100%)</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Progress value={null} variant="default">
                <ProgressLabel>Indeterminate (null)</ProgressLabel>
                <ProgressValue />
            </Progress>
        </div>
    ),
} satisfies Story

export const Animated = {
    render: () => {
        const [value, setValue] = useState(0)

        useEffect(() => {
            const id = setInterval(() => {
                setValue((v) => (v >= 100 ? 0 : v + 7))
            }, 600)
            return () => clearInterval(id)
        }, [])

        const variant: 'destructive' | 'warning' | 'success' = value < 33 ? 'destructive' : value < 66 ? 'warning' : 'success'

        return (
            <Progress value={value} variant={variant} className="w-full max-w-sm">
                <ProgressLabel>Health score</ProgressLabel>
                <ProgressValue />
            </Progress>
        )
    },
} satisfies Story

export const ComposedManually = {
    name: 'Composed manually',
    parameters: {
        docs: {
            description: {
                story:
                    'Use `ProgressTrack` + `ProgressIndicator` directly when the convenience `Progress` shell is not what you want — for example, when the consumer wants control over child order, or to render multiple indicators inside a single track.',
            },
        },
    },
    render: () => (
        <div className="flex w-full max-w-sm flex-col gap-4">
            <Progress value={73} variant="success" className="flex-row items-center gap-3">
                <ProgressLabel>Inline label</ProgressLabel>
                <ProgressValue />
            </Progress>
            <ProgressTrack>
                <ProgressIndicator variant="info" style={{ width: '64%' }} />
            </ProgressTrack>
        </div>
    ),
} satisfies Story
