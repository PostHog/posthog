import { Meta, StoryObj } from '@storybook/react'

import { Logo, Logomark } from 'lib/brand'

const meta: Meta = {
    title: 'Components/Brand Logo',
    tags: ['test-skip'],
    parameters: {
        docs: {
            description: {
                component:
                    'The PostHog logo, rendered from `@posthog/brand` via the theme- and holiday-aware `lib/brand` wrapper. ' +
                    'Pick the look with `variant` (gradient | print | mono), `layout` (landscape | stacked | logomark | wordmark), ' +
                    'and `color` (for mono). Size with the `size` token (`sm` | `md` | `lg`) — it sets the height, width follows. ' +
                    'The logomark can `jumpOnClick` and dress up for a `holiday`.',
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
            <Row label="theme-aware (default)">
                <Logo size="md" />
            </Row>
            <Row label='variant="gradient"'>
                <Logo variant="gradient" size="md" />
            </Row>
            <Row label='variant="print"'>
                <Logo variant="print" size="md" />
            </Row>
            <Row label='variant="mono" color="primary" — theme-following'>
                <Logo variant="mono" color="primary" size="md" />
            </Row>
        </div>
    ),
}

export const Sizes: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label="size sm / md / lg — the token sets height, width follows">
                <Logo size="sm" />
                <Logo size="md" />
                <Logo size="lg" />
            </Row>
            <Row label="same tokens on the logomark">
                <Logomark size="sm" />
                <Logomark size="md" />
                <Logomark size="lg" />
            </Row>
        </div>
    ),
}

export const Layouts: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label='layout="landscape" (default) vs logomark vs wordmark'>
                <Logo variant="gradient" layout="landscape" size="md" />
                <Logo variant="gradient" layout="logomark" size="md" />
                <Logo variant="gradient" layout="wordmark" size="md" />
            </Row>
            <Row label='layout="stacked" (portrait)'>
                <Logo variant="gradient" layout="stacked" size="md" />
            </Row>
        </div>
    ),
}

export const Holidays: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label='holiday="christmas"'>
                <Logomark variant="gradient" holiday="christmas" size="md" />
            </Row>
            <Row label='holiday="halloween"'>
                <Logomark variant="gradient" holiday="halloween" size="md" />
            </Row>
        </div>
    ),
}

export const JumpOnClick: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label="click me! (successive clicks jump higher)">
                <Logomark variant="gradient" jumpOnClick size="md" />
            </Row>
        </div>
    ),
}

export const MonoColors: StoryObj = {
    render: () => (
        <div className="grid grid-cols-2 gap-4 p-4">
            <div className="flex items-center justify-center bg-white rounded p-8">
                <Logo variant="mono" color="black" size="md" />
            </div>
            <div className="flex items-center justify-center bg-black rounded p-8">
                <Logo variant="mono" color="white" size="md" />
            </div>
        </div>
    ),
}
