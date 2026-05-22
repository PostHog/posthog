import type { Meta, StoryObj } from '@storybook/react'

import { semanticColors } from '@posthog/quill-tokens'

const meta = {
    title: 'Tokens/Colors',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

type ColorSwatchItem = {
    name: string
    items: ColorSwatch[]
    usages?: readonly string[]
}
type ColorSwatch = {
    className: string
    name: string
    tailwindClass: string
    value: string
}

function ColorSwatchValue({ className, name, tailwindClass, value }: ColorSwatch): React.ReactElement {
    return (
        <div className="flex gap-2 items-center">
            <div
                className={`size-16 border flex items-center justify-center ${className} rounded-sm`}
                style={{ backgroundColor: value }}
            >
                {name.includes('foreground') ? <span className="text-xs mx-auto">Aa</span> : null}
            </div>
            <div className="flex flex-col">
                <span className="font-medium">{name}</span>
                <span className="text-xs text-muted-foreground font-mono">.{tailwindClass}</span>
                <span className="text-xs text-muted-foreground font-mono">{value}</span>
            </div>
        </div>
    )
}

function ColorSwatch({ name, items, usages }: ColorSwatchItem): React.ReactElement {
    return (
        <div className="flex flex-col gap-4 mb-8">
            {name}
            <div className="grid grid-cols-[300px_300px] gap-2">
                {items[0] && <ColorSwatchValue {...items[0]} />}
                {items[1] && <ColorSwatchValue {...items[1]} />}
            </div>
            <div className="flex flex-col">
                {usages?.map((usage) => (
                    <span key={usage} className="text-xs text-muted-foreground font-mono">
                        {usage}
                    </span>
                ))}
            </div>
        </div>
    )
}

export const AllColors: Story = {
    render: () => {
        return (
            <div className="space-y-6">
                <p className="text-sm text-muted-foreground">
                    Semantic color tokens from <code className="text-xs">@posthog/quill-tokens</code>. Toggle the theme
                    in the toolbar to see dark mode values.
                </p>
                <div>
                    <ColorSwatch
                        name="Base"
                        items={[
                            {
                                className: 'bg-background',
                                name: 'background',
                                tailwindClass: 'bg-background',
                                value: semanticColors.background[0],
                            },
                            {
                                className: 'text-foreground',
                                name: 'foreground',
                                tailwindClass: 'text-foreground',
                                value: semanticColors.foreground[0],
                            },
                        ]}
                        usages={['Main background of the app']}
                    />
                    <ColorSwatch
                        name="Card"
                        items={[
                            {
                                className: 'bg-card',
                                name: 'card',
                                tailwindClass: 'bg-card',
                                value: semanticColors.card[0],
                            },
                            {
                                className: 'text-card-foreground',
                                name: 'card-foreground',
                                tailwindClass: 'text-card-foreground',
                                value: semanticColors['card-foreground'][0],
                            },
                        ]}
                        usages={['Background of cards and other surfaces like, modals, charts, etc.']}
                    />
                    <ColorSwatch
                        name="Primary"
                        items={[
                            {
                                className: 'bg-primary',
                                name: 'primary',
                                tailwindClass: 'bg-primary',
                                value: semanticColors.primary[0],
                            },
                            {
                                className: 'text-primary-foreground',
                                name: 'primary-foreground',
                                tailwindClass: 'text-primary-foreground',
                                value: semanticColors['primary-foreground'][0],
                            },
                        ]}
                        usages={['Main background of the app']}
                    />

                    <ColorSwatch
                        name="Muted"
                        items={[
                            {
                                className: 'bg-muted',
                                name: 'muted',
                                tailwindClass: 'bg-muted',
                                value: semanticColors.muted[0],
                            },
                            {
                                className: 'text-muted-foreground',
                                name: 'muted-foreground',
                                tailwindClass: 'text-muted-foreground',
                                value: semanticColors['muted-foreground'][0],
                            },
                        ]}
                        usages={['Muted background of the app']}
                    />

                    <ColorSwatch
                        name="Destructive"
                        items={[
                            {
                                className: 'bg-destructive',
                                name: 'destructive',
                                tailwindClass: 'bg-destructive',
                                value: semanticColors.destructive[0],
                            },
                            {
                                className: 'text-destructive-foreground',
                                name: 'destructive-foreground',
                                tailwindClass: 'text-destructive-foreground',
                                value: semanticColors['destructive-foreground'][0],
                            },
                        ]}
                        usages={['Destructive (used for destructive actions, errors, etc.)`']}
                    />

                    <ColorSwatch
                        name="Success"
                        items={[
                            {
                                className: 'bg-success',
                                name: 'success',
                                tailwindClass: 'bg-success',
                                value: semanticColors.success[0],
                            },
                            {
                                className: 'text-success-foreground',
                                name: 'success-foreground',
                                tailwindClass: 'text-success-foreground',
                                value: semanticColors['success-foreground'][0],
                            },
                        ]}
                        usages={['Success (used for success actions, success, etc.)`']}
                    />

                    <ColorSwatch
                        name="Warning"
                        items={[
                            {
                                className: 'bg-warning',
                                name: 'warning',
                                tailwindClass: 'bg-warning',
                                value: semanticColors.warning[0],
                            },
                            {
                                className: 'text-warning-foreground',
                                name: 'warning-foreground',
                                tailwindClass: 'text-warning-foreground',
                                value: semanticColors['warning-foreground'][0],
                            },
                        ]}
                        usages={['Warning (used for warning actions, warnings, etc.)`']}
                    />

                    <ColorSwatch
                        name="Info"
                        items={[
                            {
                                className: 'bg-info',
                                name: 'info',
                                tailwindClass: 'bg-info',
                                value: semanticColors.info[0],
                            },
                            {
                                className: 'text-info-foreground',
                                name: 'info-foreground',
                                tailwindClass: 'text-info-foreground',
                                value: semanticColors['info-foreground'][0],
                            },
                        ]}
                        usages={['Info (used for info actions, infos, etc.)`']}
                    />

                    <div className="p-2 font-mono bg-border text-foreground">
                        border/foreground: {semanticColors.border[0]}
                    </div>
                    <div className="p-2 font-mono bg-input text-foreground">
                        input/foreground: {semanticColors.input[0]}
                    </div>
                    <div className="p-2 font-mono bg-ring text-foreground">
                        ring/foreground: {semanticColors.ring[0]}
                    </div>
                </div>
            </div>
        )
    },
}
