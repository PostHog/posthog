import type { Meta, StoryObj } from '@storybook/react'
import * as React from 'react'

import { Button } from './button'
import { Heading } from './heading'
import { Highlight, type HighlightColor } from './highlight'
import { Text } from './text'

const COLORS: HighlightColor[] = ['orange', 'red', 'yellow', 'green', 'blue', 'purple']

const meta: Meta<typeof Highlight> = {
    title: 'Typography/Highlight',
    component: Highlight,
    tags: ['autodocs'],
    args: {
        children: 'self-driving',
        color: 'orange',
        animate: true,
    },
    argTypes: {
        color: {
            control: 'select',
            options: COLORS,
        },
        animate: { control: 'boolean' },
        duration: { control: { type: 'number', min: 100, step: 100 } },
        delay: { control: { type: 'number', min: 0, step: 100 } },
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const Playground = {
    render: (args) => (
        <Heading size="2xl">
            Make your product <Highlight {...args} />
        </Heading>
    ),
} satisfies Story

export const Colors = {
    render: () => (
        <div className="flex flex-col gap-3">
            {COLORS.map((color) => (
                <Heading key={color} size="xl">
                    A simpler <Highlight color={color}>{color} sidebar</Highlight>
                </Heading>
            ))}
        </div>
    ),
} satisfies Story

function Replayable({ children }: { children: (key: number) => React.ReactNode }): React.ReactElement {
    const [run, setRun] = React.useState(0)
    return (
        <div className="flex flex-col items-start gap-4">
            {children(run)}
            <Button variant="outline" onClick={() => setRun((value) => value + 1)}>
                Replay
            </Button>
        </div>
    )
}

export const Animated = {
    render: () => (
        <Replayable>
            {(run) => (
                <div key={run} className="flex flex-col gap-3">
                    <Heading size="2xl">
                        Are software factories{' '}
                        <Highlight color="purple" animate>
                            BS?
                        </Highlight>
                    </Heading>
                    <Heading size="xl">
                        Make your product{' '}
                        <Highlight color="blue" animate delay={300}>
                            self-driving
                        </Highlight>
                    </Heading>
                    <Heading size="lg">
                        <Highlight color="orange" animate delay={600}>
                            A simpler sidebar
                        </Highlight>
                    </Heading>
                </div>
            )}
        </Replayable>
    ),
} satisfies Story

export const Wrapping = {
    render: () => (
        <Replayable>
            {(run) => (
                <Text key={run} className="max-w-80">
                    Many of you told us things were hard to find.{' '}
                    <Highlight color="yellow" animate>
                        So we rebuilt the sidebar around the products you use, and moved everything else one click away
                    </Highlight>
                    . Let us know what you think.
                </Text>
            )}
        </Replayable>
    ),
} satisfies Story

const LAYOUT_COPY = 'The highlight paints behind the text. It never adds space, so line breaks stay where they were.'

export const LayoutUnchanged = {
    render: () => (
        <div className="flex max-w-72 flex-col gap-4">
            <Text>{LAYOUT_COPY}</Text>
            <Text>
                The highlight paints behind the text.{' '}
                <Highlight color="green">It never adds space, so line breaks stay where they were.</Highlight>
            </Text>
        </div>
    ),
} satisfies Story
