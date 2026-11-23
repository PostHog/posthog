import type { Meta, StoryObj } from '@storybook/react'

import { Card, CardContent, CardHeader, CardTitle, Text } from '@posthog/quill-primitives'

import { Infotip } from './infotip'

const meta: Meta<typeof Infotip> = {
    title: 'Components/Infotip',
    component: Infotip,
    tags: ['autodocs'],
    args: {
        label: 'About average position',
        children: 'Where your site appears among the cited sources, on average. 1 is first.',
        side: 'top',
        align: 'center',
        delay: 100,
    },
    argTypes: {
        side: { control: 'inline-radio', options: ['top', 'right', 'bottom', 'left'] },
        align: { control: 'inline-radio', options: ['start', 'center', 'end'] },
        delay: { control: { type: 'number', min: 0, step: 50 } },
        children: { control: 'text' },
    },
    decorators: [
        (Story) => (
            <div className="flex min-h-48 items-center justify-center p-8">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const NextToATitle: Story = {
    render: (args) => (
        <Card className="w-80">
            <CardHeader>
                <CardTitle className="flex items-center gap-1">
                    Share of answers that cite you
                    <Infotip {...args} label="About share of answers that cite you">
                        Of the answers checked, the share that link to your site as a source.
                    </Infotip>
                </CardTitle>
            </CardHeader>
            <CardContent>42%</CardContent>
        </Card>
    ),
}

export const InSmallText: Story = {
    render: (args) => (
        <Text size="xs" variant="muted" className="flex items-center gap-1">
            Updated hourly
            <Infotip {...args} label="About the update schedule">
                New answers are checked once an hour, so the latest change can take up to an hour to show.
            </Infotip>
        </Text>
    ),
}

export const Sides: Story = {
    render: (args) => (
        <div className="grid grid-cols-2 gap-x-16 gap-y-8">
            {(['top', 'right', 'bottom', 'left'] as const).map((side) => (
                <span key={side} className="flex items-center gap-1 text-sm">
                    {side}
                    <Infotip {...args} side={side} label={`About ${side}`}>
                        Opens on the {side}, and flips when there is no room.
                    </Infotip>
                </span>
            ))}
        </div>
    ),
}

export const WithALink: Story = {
    render: (args) => (
        <span className="flex items-center gap-1 text-sm">
            Mentioned
            <Infotip {...args} label="About mentioned">
                The answer names your brand, with or without a link.{' '}
                {/* eslint-disable-next-line react/forbid-elements -- plain link in a storybook demo */}
                <a href="https://posthog.com/docs" className="underline">
                    Read the docs
                </a>
            </Infotip>
        </span>
    ),
}

export const LongText: Story = {
    args: {
        label: 'About visibility score',
        children:
            'The score combines how often answers mention you, how often they cite your site, and where your site appears among the cited sources. It wraps at a readable width rather than growing across the page.',
    },
}
