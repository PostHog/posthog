import type { Meta, StoryObj } from '@storybook/react'

import { Card, CardContent, CardHeader, CardTitle } from '@posthog/quill-primitives'

import { Infotip } from './infotip'

const meta: Meta<typeof Infotip> = {
    title: 'Components/Infotip',
    component: Infotip,
    tags: ['autodocs'],
}

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
    args: {
        label: 'About average position',
        children: 'Where your site appears among the cited sources, on average. 1 is first.',
    },
}

export const NextToATitle: Story = {
    render: () => (
        <Card className="w-80">
            <CardHeader>
                <CardTitle className="flex items-center gap-1">
                    Share of answers that cite you
                    <Infotip label="About share of answers that cite you">
                        Of the answers checked, the share that link to your site as a source.
                    </Infotip>
                </CardTitle>
            </CardHeader>
            <CardContent>42%</CardContent>
        </Card>
    ),
}

export const WithALink: Story = {
    render: () => (
        <div className="flex items-center gap-1 text-sm">
            Mentioned
            <Infotip label="About mentioned">
                The answer names your brand, with or without a link.{' '}
                <a href="https://posthog.com/docs" className="underline">
                    Read the docs
                </a>
            </Infotip>
        </div>
    ),
}
