import type { Meta, StoryObj } from '@storybook/react'

import { shadow } from '@posthog/quill-tokens'

const meta = {
    title: 'Tokens/Shadows',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

type ShadowKey = keyof typeof shadow

// Static map so Tailwind's class scanner sees each utility as a literal
// string — template-string concatenation (`shadow-${name}`) is not picked
// up by the JIT compiler and would render with no shadow.
const shadowClass: Record<ShadowKey, string> = {
    sm: 'shadow-sm',
    md: 'shadow-md',
    lg: 'shadow-lg',
}

const shadowOrder: ShadowKey[] = ['sm', 'md', 'lg']

function ShadowSwatch({ name }: { name: ShadowKey }): React.ReactElement {
    const value = shadow[name]
    return (
        <div className="flex gap-4 items-center">
            <div
                className={`size-24 rounded-md bg-card border border-border ${shadowClass[name]} flex items-center justify-center`}
            >
                <span className="text-xs text-muted-foreground font-mono">shadow-{name}</span>
            </div>
            <div className="flex flex-col">
                <span className="font-medium">{name}</span>
                <span className="text-xs text-muted-foreground font-mono">.shadow-{name}</span>
                <span className="text-xs text-muted-foreground font-mono break-all max-w-md">{value}</span>
            </div>
        </div>
    )
}

export const AllShadows: Story = {
    render: () => (
        <div className="space-y-8 p-8">
            <div>
                <p className="text-sm text-muted-foreground">
                    Shadow tokens from <code className="text-xs">@posthog/quill-tokens</code>. Toggle the theme in the
                    toolbar to check that every shadow resolves correctly in both light and dark mode — no dangling{' '}
                    <code className="text-xs">var(--*)</code> references should fall back to transparent.
                </p>
            </div>
            <div className="flex flex-col gap-8">
                {shadowOrder.map((name) => (
                    <ShadowSwatch key={name} name={name} />
                ))}
            </div>
        </div>
    ),
}
