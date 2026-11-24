import type { Meta, StoryObj } from '@storybook/react'
import { SparklesIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from './button'
import {
    Callout,
    CalloutActions,
    CalloutClose,
    CalloutContent,
    CalloutDescription,
    CalloutIcon,
    type CalloutProps,
    CalloutTitle,
} from './callout'

const tones = ['default', 'info', 'success', 'warning', 'destructive'] as const

type PlaygroundArgs = Pick<CalloutProps, 'tone' | 'toneLabel'> & {
    title: string
    description: string
    action: string
    icon: boolean
    dismissible: boolean
}

const meta: Meta<typeof Callout> = {
    title: 'Primitives/Callout',
    component: Callout,
    tags: ['autodocs'],
    // The showcase stories below render fixed examples, so only Playground takes controls.
    parameters: { controls: { disable: true } },
}

export default meta
type Story = StoryObj<typeof meta>

export const Playground: StoryObj<PlaygroundArgs> = {
    parameters: { controls: { disable: false } },
    args: {
        tone: 'warning',
        title: '',
        description: "This insight's date range goes beyond your 1-year data retention.",
        action: 'Upgrade plan',
        icon: true,
        dismissible: true,
    },
    argTypes: {
        tone: { control: 'select', options: tones },
        toneLabel: {
            control: 'text',
            description: 'Screen reader prefix. Leave empty for the tone default.',
        },
        title: { control: 'text', description: 'Leave empty for no title.' },
        description: { control: 'text' },
        action: { control: 'text', description: 'Leave empty for no action.' },
        icon: { control: 'boolean' },
        dismissible: { control: 'boolean' },
    },
    render: ({ tone, toneLabel, title, description, action, icon, dismissible }) => (
        <div className="max-w-xl">
            <Callout tone={tone} toneLabel={toneLabel || undefined}>
                {icon && <CalloutIcon />}
                <CalloutContent>
                    {title && <CalloutTitle>{title}</CalloutTitle>}
                    <CalloutDescription>{description}</CalloutDescription>
                </CalloutContent>
                {action && (
                    <CalloutActions>
                        <Button variant="outline">{action}</Button>
                    </CalloutActions>
                )}
                {dismissible && <CalloutClose onClick={() => {}} />}
            </Callout>
        </div>
    ),
}

export const Tones: Story = {
    render: () => (
        <div className="flex max-w-xl flex-col gap-3">
            {tones.map((tone) => (
                <Callout key={tone} tone={tone}>
                    <CalloutIcon />
                    <CalloutContent>
                        <CalloutDescription>This is a {tone} callout.</CalloutDescription>
                    </CalloutContent>
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
                <CalloutContent>
                    <CalloutTitle>Your event volume is close to the billing limit</CalloutTitle>
                    <CalloutDescription>
                        When the project reaches the limit, PostHog stops ingesting new events until the next billing
                        period. Increase the limit or reduce the events you capture. The description does not clamp, so
                        long text wraps onto as many lines as it needs.
                    </CalloutDescription>
                </CalloutContent>
            </Callout>
            <Callout tone="destructive">
                <CalloutIcon />
                <CalloutContent>
                    <CalloutTitle>Could not load this insight</CalloutTitle>
                    <CalloutDescription>The query timed out after 60 seconds.</CalloutDescription>
                </CalloutContent>
            </Callout>
        </div>
    ),
}

export const RichDescription: Story = {
    render: () => (
        <div className="max-w-xl">
            <Callout tone="warning">
                <CalloutIcon />
                <CalloutContent>
                    <CalloutDescription>
                        <span>
                            Some warehouse tables this insight reads are out of date, so its results may not be current:
                        </span>
                        <ul className="mt-1 list-disc ps-4">
                            <li>
                                <code>stripe.invoices</code>: last synced 3 days ago
                            </li>
                            <li>
                                <code>hubspot.contacts</code>: last synced 2 days ago
                            </li>
                        </ul>
                        {/* eslint-disable-next-line react/forbid-elements */}
                        <a href="#">Open the sync settings</a>
                    </CalloutDescription>
                </CalloutContent>
            </Callout>
        </div>
    ),
}

export const Dismissible: Story = {
    render: function DismissibleStory() {
        const [open, setOpen] = useState(true)
        if (!open) {
            return <Button onClick={() => setOpen(true)}>Show the callout again</Button>
        }
        return (
            <div className="max-w-xl">
                <Callout tone="info">
                    <CalloutIcon />
                    <CalloutContent>
                        <CalloutDescription>
                            Funnels now count conversions inside the window you pick. Older funnels keep their setting.
                        </CalloutDescription>
                    </CalloutContent>
                    <CalloutClose onClick={() => setOpen(false)} />
                </Callout>
            </div>
        )
    },
}

export const ActionAndClose: Story = {
    render: () => (
        <div className="max-w-xl">
            <Callout tone="warning">
                <CalloutIcon />
                <CalloutContent>
                    <CalloutDescription>
                        This insight's date range goes beyond your 1-year data retention, so events older than that
                        aren't included.
                    </CalloutDescription>
                </CalloutContent>
                <CalloutActions>
                    <Button variant="outline">Upgrade plan</Button>
                </CalloutActions>
                <CalloutClose onClick={() => {}} />
            </Callout>
        </div>
    ),
}

/** When the text would get narrower than 16rem, the actions wrap to a row under it. The close button stays in the top-right corner. */
export const Narrow: Story = {
    render: () => (
        <div className="flex w-80 flex-col gap-3">
            <Callout tone="warning">
                <CalloutIcon />
                <CalloutContent>
                    <CalloutDescription>
                        This insight's date range goes beyond your 1-year data retention, so events older than that
                        aren't included.
                    </CalloutDescription>
                </CalloutContent>
                <CalloutActions>
                    <Button variant="outline">Upgrade plan</Button>
                </CalloutActions>
                <CalloutClose onClick={() => {}} />
            </Callout>
            <Callout tone="destructive">
                <CalloutIcon />
                <CalloutContent>
                    <CalloutTitle>Email sending is suspended</CalloutTitle>
                    <CalloutDescription>
                        Too many messages bounced. Contact support to restore sending.
                    </CalloutDescription>
                </CalloutContent>
                <CalloutActions>
                    <Button variant="outline">Contact support</Button>
                </CalloutActions>
            </Callout>
        </div>
    ),
}

export const CustomIcon: Story = {
    render: () => (
        <div className="max-w-xl">
            <Callout tone="info">
                <CalloutIcon>
                    <SparklesIcon />
                </CalloutIcon>
                <CalloutContent>
                    <CalloutDescription>
                        PostHog AI wrote this summary. Check it before you share it.
                    </CalloutDescription>
                </CalloutContent>
            </Callout>
        </div>
    ),
}

export const NoIcon: Story = {
    render: () => (
        <div className="max-w-xl">
            <Callout>
                <CalloutContent>
                    <CalloutDescription>A plain note with no icon, on the muted default surface.</CalloutDescription>
                </CalloutContent>
            </Callout>
        </div>
    ),
}

/** Add a live-region role only when the callout appears after a user action. */
export const LiveRegion: Story = {
    render: function LiveRegionStory() {
        const [failed, setFailed] = useState(false)
        return (
            <div className="flex max-w-xl flex-col items-start gap-3">
                <Button variant="outline" onClick={() => setFailed(true)}>
                    Save
                </Button>
                {failed && (
                    <Callout tone="destructive" role="alert">
                        <CalloutIcon />
                        <CalloutContent>
                            <CalloutDescription>
                                Could not save. Check your connection and try again.
                            </CalloutDescription>
                        </CalloutContent>
                    </Callout>
                )}
            </div>
        )
    },
}
