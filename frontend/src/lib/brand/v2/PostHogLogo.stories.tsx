import { Meta, StoryObj } from '@storybook/react'

import { PostHogLogo } from './PostHogLogo'

const meta: Meta = {
    title: 'Components/Brand Logos (Redesign)',
    tags: ['test-skip'],
    parameters: {
        docs: {
            description: {
                component:
                    'Redesigned PostHog logo, copied from posthog.com. One props-based component: pick the look with ' +
                    '`variant` (gradient | print | mono), `color` (for mono), `wordmark`, `stacked`, and `code`. ' +
                    'For a theme-following monochrome mark use `variant="mono" color="primary"` — `fill-primary` flips with the theme.',
            },
        },
    },
}
export default meta

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs text-muted uppercase tracking-wide">{label}</span>
            <div className="flex items-end gap-8 flex-wrap">{children}</div>
        </div>
    )
}

export const Variants: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label='variant="gradient" (default)'>
                <PostHogLogo className="h-8 w-auto" />
            </Row>
            <Row label='variant="print"'>
                <PostHogLogo variant="print" className="h-8 w-auto" />
            </Row>
            <Row label='variant="mono" color="primary" — theme-following'>
                <PostHogLogo variant="mono" color="primary" className="h-8 w-auto" />
            </Row>
        </div>
    ),
}

export const Composition: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label="wordmark (default) vs icon only">
                <PostHogLogo className="h-8 w-auto" />
                <PostHogLogo wordmark={false} className="h-8 w-auto" />
            </Row>
            <Row label="stacked (portrait)">
                <PostHogLogo stacked className="h-20 w-auto" />
                <PostHogLogo stacked variant="mono" color="primary" className="h-20 w-auto" />
            </Row>
            <Row label="code wordmark">
                <PostHogLogo code className="h-8 w-auto" />
            </Row>
        </div>
    ),
}

export const MonoColors: StoryObj = {
    render: () => (
        <div className="grid grid-cols-2 gap-4 p-4">
            <div className="flex items-center justify-center bg-white rounded p-8">
                <PostHogLogo variant="mono" color="black" className="h-8 w-auto" />
            </div>
            <div className="flex items-center justify-center bg-black rounded p-8">
                <PostHogLogo variant="mono" color="white" className="h-8 w-auto" />
            </div>
        </div>
    ),
}
