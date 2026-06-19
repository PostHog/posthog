import { Meta, StoryObj } from '@storybook/react'

import { PostHogLogomarkV2 } from './PostHogLogomarkV2'
import { PostHogLogoV2 } from './PostHogLogoV2'
import { PostHogWordmarkLogoV2 } from './PostHogWordmarkLogoV2'

const meta: Meta = {
    title: 'Components/Brand Logos (Redesign)',
    parameters: {
        docs: {
            description: {
                component:
                    'Redesigned PostHog logo set, added alongside the existing brand components. Opt in via `lib/brand/v2`. Raw SVG/PNG assets live in `public/brand-v2/`.',
            },
        },
    },
}
export default meta

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs text-muted uppercase tracking-wide">{label}</span>
            <div className="flex items-center gap-6 flex-wrap">{children}</div>
        </div>
    )
}

export const Components: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label="PostHogLogoV2 — primary gradient lockup">
                <PostHogLogoV2 className="h-7 w-auto" />
                <PostHogLogoV2 className="h-10 w-auto" />
            </Row>
            <Row label="PostHogLogomarkV2 — gradient icon">
                <PostHogLogomarkV2 className="h-6 w-auto" />
                <PostHogLogomarkV2 className="h-10 w-auto" />
                <PostHogLogomarkV2 className="h-16 w-auto" />
            </Row>
            <Row label="PostHogWordmarkLogoV2 — monochrome, follows currentColor">
                <PostHogWordmarkLogoV2 className="h-7 w-auto text-primary" />
            </Row>
        </div>
    ),
}

export const MonochromeOnLightAndDark: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex items-center justify-center bg-white rounded p-8">
                <PostHogWordmarkLogoV2 className="h-8 w-auto text-black" />
            </div>
            <div className="flex items-center justify-center bg-black rounded p-8">
                <PostHogWordmarkLogoV2 className="h-8 w-auto text-white" />
            </div>
        </div>
    ),
}
