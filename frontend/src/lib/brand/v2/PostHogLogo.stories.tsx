import { Meta, StoryObj } from '@storybook/react'

import { PostHogLogo } from './PostHogLogo'
import { PostHogLogoBlack } from './PostHogLogoBlack'
import { PostHogLogoColor } from './PostHogLogoColor'
import { PostHogLogoGradient } from './PostHogLogoGradient'
import { PostHogLogoGradientAlt } from './PostHogLogoGradientAlt'
import { PostHogLogomark } from './PostHogLogomark'
import { PostHogLogomarkColor } from './PostHogLogomarkColor'
import { PostHogLogoPortrait } from './PostHogLogoPortrait'
import { PostHogLogoWhite } from './PostHogLogoWhite'
import { PostHogWordmarkWhite } from './PostHogWordmarkWhite'

const meta: Meta = {
    title: 'Components/Brand Logos (Redesign)',
    parameters: {
        docs: {
            description: {
                component:
                    'Redesigned PostHog logo set, added alongside the existing brand components. Opt in via `lib/brand/v2`. ' +
                    'A bare name (`PostHogLogo`) is theme-adaptive — gradient in light mode, solid white in dark mode, swapped via ' +
                    'CSS off `[theme="dark"]`. Explicit treatments (`Gradient`, `Color`, `Black`, `White`) are the exact source assets, ' +
                    'values untouched. Toggle the Storybook theme to see the adaptive ones swap. Raw assets live in `public/brand-v2/`.',
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

// The adaptive components swap gradient <-> white with the Storybook theme toolbar.
export const Adaptive: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label="PostHogLogo — adaptive landscape (gradient in light, white in dark)">
                <PostHogLogo className="h-8 w-auto" />
            </Row>
            <Row label="PostHogLogoPortrait — adaptive portrait">
                <PostHogLogoPortrait className="h-24 w-auto" />
            </Row>
            <Row label="PostHogLogomark — gradient icon (both themes)">
                <PostHogLogomark className="h-8 w-auto" />
                <PostHogLogomark className="h-12 w-auto" />
                <PostHogLogomark className="h-16 w-auto" />
            </Row>
        </div>
    ),
}

// Fixed treatments — shown on the background each is designed for.
export const FixedVariants: StoryObj = {
    render: () => (
        <div className="flex flex-col gap-8 p-4">
            <Row label="Gradient / color / black — on light">
                <div className="flex items-end gap-8 bg-white rounded p-6">
                    <PostHogLogoGradient className="h-8 w-auto" />
                    <PostHogLogoGradientAlt className="h-8 w-auto" />
                    <PostHogLogoColor className="h-8 w-auto" />
                    <PostHogLogoBlack className="h-8 w-auto" />
                    <PostHogLogomarkColor className="h-8 w-auto" />
                </div>
            </Row>
            <Row label="White variants — on dark">
                <div className="flex items-end gap-8 bg-black rounded p-6">
                    <PostHogLogoWhite className="h-8 w-auto" />
                    <PostHogWordmarkWhite className="h-6 w-auto" />
                </div>
            </Row>
        </div>
    ),
}
