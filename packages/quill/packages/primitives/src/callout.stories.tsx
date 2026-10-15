import type { Meta, StoryObj } from '@storybook/react'
import { SparklesIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import { Callout, CalloutClose, CalloutIcon } from './callout'
import { ItemActions, ItemContent, ItemDescription, ItemTitle } from './item'

const meta: Meta<typeof Callout> = {
    title: 'Primitives/Callout',
    component: Callout,
    tags: ['autodocs'],
    argTypes: {
        tone: {
            control: 'select',
            options: ['default', 'info', 'success', 'warning', 'destructive'],
        },
    },
}

export default meta
type Story = StoryObj<typeof meta>

const tones = ['default', 'info', 'success', 'warning', 'destructive'] as const

export const Tones: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            {tones.map((tone) => (
                <Callout key={tone} tone={tone}>
                    <CalloutIcon />
                    <ItemContent>
                        <ItemTitle>This is a {tone} callout.</ItemTitle>
                    </ItemContent>
                </Callout>
            ))}
        </div>
    ),
}

export const TitleAndDescription: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            <Callout tone="warning">
                <CalloutIcon />
                <ItemContent>
                    <ItemTitle>Your event volume is close to the billing limit</ItemTitle>
                    <ItemDescription>
                        When the project reaches the limit, PostHog stops ingesting new events until the next billing
                        period. Increase the limit or reduce the events you capture. The description does not clamp, so
                        long text wraps onto as many lines as it needs.
                    </ItemDescription>
                </ItemContent>
            </Callout>
            <Callout tone="destructive">
                <CalloutIcon />
                <ItemContent>
                    <ItemTitle>Could not load this insight</ItemTitle>
                    <ItemDescription>The query timed out after 60 seconds.</ItemDescription>
                </ItemContent>
            </Callout>
        </div>
    ),
}

export const WithAction: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            <Callout tone="info">
                <CalloutIcon />
                <ItemContent>
                    <ItemTitle>Session replay is off for this project</ItemTitle>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline">Turn on</Button>
                </ItemActions>
            </Callout>
            <Callout tone="warning">
                <CalloutIcon />
                <ItemContent>
                    <ItemTitle>Two flags use this cohort</ItemTitle>
                    <ItemDescription>Changes to the cohort also change who sees those flags.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline">View flags</Button>
                </ItemActions>
                <CalloutClose />
            </Callout>
        </div>
    ),
}

function DismissibleExample(): React.ReactElement {
    const [open, setOpen] = useState(true)
    if (!open) {
        return (
            <Button variant="outline" onClick={() => setOpen(true)}>
                Show the callout again
            </Button>
        )
    }
    return (
        <Callout tone="success">
            <CalloutIcon />
            <ItemContent>
                <ItemTitle>Your data warehouse source is connected</ItemTitle>
            </ItemContent>
            <CalloutClose onClick={() => setOpen(false)} />
        </Callout>
    )
}

export const Dismissible: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            <DismissibleExample />
        </div>
    ),
}

export const CustomIconAndNoIcon: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            <Callout tone="info">
                <CalloutIcon>
                    <SparklesIcon />
                </CalloutIcon>
                <ItemContent>
                    <ItemTitle>PostHog AI can write this query for you</ItemTitle>
                </ItemContent>
            </Callout>
            <Callout>
                <ItemContent>
                    <ItemTitle>A callout with no icon</ItemTitle>
                </ItemContent>
            </Callout>
        </div>
    ),
}

export const LiveRegion: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            <Callout tone="destructive" role="alert">
                <CalloutIcon />
                <ItemContent>
                    <ItemTitle>Could not save the dashboard</ItemTitle>
                    <ItemDescription>
                        Use role="alert" only when the callout appears after a user action and screen readers must
                        announce it.
                    </ItemDescription>
                </ItemContent>
                <CalloutClose />
            </Callout>
        </div>
    ),
}
