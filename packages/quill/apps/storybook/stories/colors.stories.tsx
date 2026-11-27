import type { Meta, StoryObj } from '@storybook/react'
import { useEffect, useState } from 'react'

import { semanticColors } from '@posthog/quill-tokens'

const meta = {
    title: 'Tokens/Colors',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

type TokenName = keyof typeof semanticColors

const cssVar = (token: TokenName): string => `var(--${token})`

// ── Contrast ──────────────────────────────────────────

type Rgb = [number, number, number]

/**
 * Paints each token onto a 1x1 canvas, stacked over `--background`, and reads
 * the pixel back. That resolves oklch, color-mix and alpha to the sRGB the eye
 * actually sees, which a computed-style string cannot give us.
 */
function resolveStack(layers: string[]): Rgb | null {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    const ctx = canvas.getContext('2d', { willReadFrequently: true })
    if (!ctx) {
        return null
    }
    const probe = document.createElement('div')
    document.body.appendChild(probe)
    for (const layer of ['var(--background)', ...layers]) {
        probe.style.color = layer
        ctx.fillStyle = getComputedStyle(probe).color
        ctx.fillRect(0, 0, 1, 1)
    }
    probe.remove()
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data
    return [r, g, b]
}

function luminance([r, g, b]: Rgb): number {
    const channel = (c: number): number => {
        const s = c / 255
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

function contrastRatio(fg: Rgb, bg: Rgb): number {
    const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a)
    return (hi + 0.05) / (lo + 0.05)
}

/** Re-renders when the toolbar flips `<html class="dark">`, so ratios track the theme. */
function useThemeKey(): string {
    const [key, setKey] = useState(() => document.documentElement.className)
    useEffect(() => {
        const observer = new MutationObserver(() => setKey(document.documentElement.className))
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])
    return key
}

function Contrast({ fg, bg }: { fg: TokenName; bg?: TokenName }): React.ReactElement {
    const themeKey = useThemeKey()
    const [ratio, setRatio] = useState<number | null>(null)

    useEffect(() => {
        const bgLayers = bg ? [cssVar(bg)] : []
        const bgRgb = resolveStack(bgLayers)
        const fgRgb = resolveStack([...bgLayers, cssVar(fg)])
        setRatio(bgRgb && fgRgb ? contrastRatio(fgRgb, bgRgb) : null)
    }, [fg, bg, themeKey])

    if (ratio === null) {
        return <span className="text-xs text-subtle-foreground tabular-nums">…</span>
    }
    const grade = ratio >= 7 ? 'AAA' : ratio >= 4.5 ? 'AA' : ratio >= 3 ? 'AA large' : 'Fail'
    const passes = ratio >= 4.5
    return (
        <span
            className={`inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] font-medium tabular-nums ${
                passes
                    ? 'bg-card/90 text-muted-foreground ring-1 ring-border'
                    : 'bg-destructive text-destructive-foreground ring-1 ring-destructive-foreground/20'
            }`}
        >
            {ratio.toFixed(1)}:1
            <span className="opacity-70">{grade}</span>
        </span>
    )
}

// ── Layout ────────────────────────────────────────────

function Section({
    title,
    description,
    children,
}: {
    title: string
    description: React.ReactNode
    children: React.ReactNode
}): React.ReactElement {
    return (
        <section className="flex flex-col gap-5 border-t border-border pt-8">
            <header className="flex flex-col gap-1.5 max-w-prose">
                <h2 className="text-lg font-semibold tracking-tight text-foreground">{title}</h2>
                <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
            </header>
            {children}
        </section>
    )
}

function Eyebrow({ children }: { children: React.ReactNode }): React.ReactElement {
    return <span className="text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">{children}</span>
}

function TokenLabel({ token, note }: { token: TokenName; note?: string }): React.ReactElement {
    return (
        <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-sm font-medium text-foreground">{token}</span>
            <code className="text-xs text-muted-foreground">.{semanticColors[token][2]}</code>
            {note ? <span className="text-xs text-subtle-foreground">{note}</span> : null}
        </div>
    )
}

function Code({ children }: { children: React.ReactNode }): React.ReactElement {
    return <code className="rounded-sm bg-fill-hover px-1 py-px text-[0.85em] text-foreground">{children}</code>
}

// ── Sections ──────────────────────────────────────────

const SURFACES: { token: TokenName; note: string }[] = [
    { token: 'background', note: 'App canvas' },
    { token: 'chrome', note: 'Toolbars, menubars, nav' },
    { token: 'muted', note: 'Subdued rows and wells' },
    { token: 'card', note: 'Cards, modals, popovers' },
]

function Surfaces(): React.ReactElement {
    return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {SURFACES.map(({ token, note }) => (
                <div key={token} className="flex flex-col gap-3">
                    <div
                        className="h-24 rounded-md border border-border shadow-[inset_0_1px_0_rgb(255_255_255/0.04)]"
                        style={{ background: cssVar(token) }}
                    />
                    <TokenLabel token={token} note={note} />
                </div>
            ))}
        </div>
    )
}

const TEXT_RAMP: { token: TokenName; sample: string; size: string; note: string }[] = [
    {
        token: 'foreground',
        sample: 'Primary text',
        size: 'text-2xl font-semibold tracking-tight',
        note: 'Headings, body',
    },
    {
        token: 'muted-foreground',
        sample: 'Secondary text and descriptions',
        size: 'text-base',
        note: 'Descriptions, labels',
    },
    {
        token: 'subtle-foreground',
        sample: 'Tertiary meta, timestamps, filenames',
        size: 'text-sm',
        note: 'One step below muted',
    },
]

function TextRamp(): React.ReactElement {
    return (
        <div className="overflow-hidden rounded-lg border border-border">
            <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-6 px-5 py-2 border-b border-border bg-muted">
                <Eyebrow>Token</Eyebrow>
                <Eyebrow>On background</Eyebrow>
                <Eyebrow>On card</Eyebrow>
            </div>
            {TEXT_RAMP.map(({ token, sample, size, note }) => (
                <div
                    key={token}
                    className="grid grid-cols-[1fr_auto_auto] items-center gap-x-6 px-5 py-4 border-b border-border last:border-b-0"
                >
                    <div className="flex flex-col gap-2 min-w-0">
                        <span className={size} style={{ color: cssVar(token) }}>
                            {sample}
                        </span>
                        <TokenLabel token={token} note={note} />
                    </div>
                    <Contrast fg={token} />
                    <Contrast fg={token} bg="card" />
                </div>
            ))}
        </div>
    )
}

function Brand(): React.ReactElement {
    return (
        <div className="grid md:grid-cols-[2fr_1fr] gap-4">
            <div
                className="flex flex-col justify-between gap-6 rounded-lg p-5 min-h-36"
                style={{ background: cssVar('primary'), color: cssVar('primary-foreground') }}
            >
                <span className="text-xl font-semibold tracking-tight">primary</span>
                <div className="flex items-end justify-between gap-4">
                    <code className="text-xs opacity-80">.bg-primary .text-primary-foreground</code>
                    <Contrast fg="primary-foreground" bg="primary" />
                </div>
            </div>
            <div
                className="flex flex-col justify-between gap-6 rounded-lg p-5 min-h-36"
                style={{ background: cssVar('foreground'), color: cssVar('background') }}
            >
                <span className="text-sm opacity-80">Inverted surface, e.g. a tooltip</span>
                <div className="flex flex-col gap-1">
                    <span
                        className="text-xl font-semibold tracking-tight"
                        style={{ color: cssVar('primary-on-foreground') }}
                    >
                        primary-on-foreground
                    </span>
                    <code className="text-xs opacity-80">.text-primary-on-foreground</code>
                </div>
            </div>
        </div>
    )
}

const STATUSES = [
    { token: 'destructive', note: 'Errors, destructive actions' },
    { token: 'success', note: 'Success, healthy states' },
    { token: 'warning', note: 'Warnings, degraded states' },
    { token: 'info', note: 'Neutral information' },
    { token: 'completed', note: 'Terminal done, e.g. merged' },
] as const

const STATUS_GRID = 'grid grid-cols-[minmax(9rem,0.7fr)_repeat(4,minmax(0,1fr))]'

function StatusCell({ children, code }: { children: React.ReactNode; code: string }): React.ReactElement {
    return (
        <div className="flex flex-col gap-2 px-4 py-4 min-w-0">
            {children}
            <code className="text-xs text-muted-foreground break-words">{code}</code>
        </div>
    )
}

function StatusRow({ token, note }: (typeof STATUSES)[number]): React.ReactElement {
    const fill = token as TokenName
    const fg = `${token}-foreground` as TokenName
    return (
        <div className={`${STATUS_GRID} border-b border-border last:border-b-0`}>
            <div className="flex flex-col gap-1 px-4 py-4">
                <span className="text-sm font-semibold capitalize text-foreground">{token}</span>
                <span className="text-xs text-muted-foreground">{note}</span>
            </div>
            <StatusCell code={`.bg-${token}`}>
                <div
                    className="flex items-center justify-between gap-2 rounded-md px-3 py-2"
                    style={{ background: cssVar(fill), color: cssVar(fg) }}
                >
                    <span className="text-sm font-medium truncate">Label</span>
                    <Contrast fg={fg} bg={fill} />
                </div>
            </StatusCell>
            <StatusCell code={`.bg-${token}/50 .border-${fg}/20`}>
                <div
                    className="rounded-md border px-3 py-2 text-sm font-medium truncate"
                    style={{
                        background: `color-mix(in oklab, ${cssVar(fill)} 50%, transparent)`,
                        borderColor: `color-mix(in oklab, ${cssVar(fg)} 20%, transparent)`,
                        color: cssVar(fg),
                    }}
                >
                    Callout
                </div>
            </StatusCell>
            <StatusCell code={`.text-${fg}`}>
                <div className="flex items-center justify-between gap-2 py-2">
                    <span className="text-sm font-medium truncate" style={{ color: cssVar(fg) }}>
                        Status text
                    </span>
                    <Contrast fg={fg} bg="card" />
                </div>
            </StatusCell>
            <StatusCell code={`.text-${token}`}>
                <div className="flex items-center justify-between gap-2 py-2">
                    <span className="text-sm font-medium line-through truncate" style={{ color: cssVar(fill) }}>
                        Status text
                    </span>
                    <Contrast fg={fill} bg="card" />
                </div>
            </StatusCell>
        </div>
    )
}

function Status(): React.ReactElement {
    return (
        <div className="overflow-hidden rounded-lg border border-border bg-card">
            <div className={`${STATUS_GRID} border-b border-border bg-muted`}>
                {['Token', 'Fill', 'Subtle tint', 'Text and icons', "Don't: bare token as text"].map((label) => (
                    <div key={label} className="px-4 py-2">
                        <Eyebrow>{label}</Eyebrow>
                    </div>
                ))}
            </div>
            {STATUSES.map((status) => (
                <StatusRow key={status.token} {...status} />
            ))}
        </div>
    )
}

const LINES: { token: TokenName; note: string; sample: React.CSSProperties }[] = [
    { token: 'border', note: 'Dividers, card edges', sample: { borderColor: cssVar('border') } },
    { token: 'input', note: 'Form control edges', sample: { borderColor: cssVar('input') } },
    {
        token: 'ring',
        note: 'Focus rings',
        sample: {
            borderColor: cssVar('border'),
            boxShadow: `0 0 0 2px ${cssVar('background')}, 0 0 0 4px ${cssVar('ring')}`,
        },
    },
]

function Lines(): React.ReactElement {
    return (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {LINES.map(({ token, note, sample }) => (
                <div key={token} className="flex flex-col gap-3">
                    <div className="flex h-20 items-center justify-center rounded-md bg-card border border-border">
                        <div className="h-9 w-3/5 rounded-md border bg-card" style={sample} />
                    </div>
                    <TokenLabel token={token} note={note} />
                </div>
            ))}
        </div>
    )
}

const FILLS: { token: TokenName; note: string }[] = [
    { token: 'fill-hover', note: 'Pointer over' },
    { token: 'fill-selected', note: 'Current item' },
    { token: 'fill-expanded', note: 'Open menu trigger' },
]

const FILL_SURFACES: TokenName[] = ['background', 'muted', 'card']

function Fills(): React.ReactElement {
    return (
        <div className="overflow-hidden rounded-lg border border-border">
            <div className="grid grid-cols-[minmax(10rem,1fr)_repeat(3,minmax(0,1fr))] border-b border-border">
                <div className="px-4 py-2 bg-muted">
                    <Eyebrow>Token</Eyebrow>
                </div>
                {FILL_SURFACES.map((surface) => (
                    <div key={surface} className="px-4 py-2 bg-muted">
                        <Eyebrow>On {surface}</Eyebrow>
                    </div>
                ))}
            </div>
            {FILLS.map(({ token, note }) => (
                <div
                    key={token}
                    className="grid grid-cols-[minmax(10rem,1fr)_repeat(3,minmax(0,1fr))] border-b border-border last:border-b-0"
                >
                    <div className="px-4 py-3">
                        <TokenLabel token={token} note={note} />
                    </div>
                    {FILL_SURFACES.map((surface) => (
                        <div key={surface} className="flex items-center p-3" style={{ background: cssVar(surface) }}>
                            <div
                                className="w-full rounded-md px-3 py-2 text-sm text-foreground"
                                style={{ background: cssVar(token) }}
                            >
                                Menu item
                            </div>
                        </div>
                    ))}
                </div>
            ))}
        </div>
    )
}

export const AllColors: Story = {
    render: () => {
        return (
            <div className="mx-auto flex max-w-6xl flex-col gap-10 px-2 py-4">
                <header className="flex flex-col gap-2 max-w-prose">
                    <Eyebrow>@posthog/quill-tokens</Eyebrow>
                    <h1 className="text-3xl font-semibold tracking-tight text-foreground">Colors</h1>
                    <p className="text-base text-muted-foreground leading-relaxed">
                        Semantic tokens, grouped by job. Swatches read the live CSS variables, so toggle the theme in
                        the toolbar to see dark mode. Contrast ratios are measured against the surface each token sits
                        on.
                    </p>
                </header>

                <Section title="Surfaces" description="The layers content sits on, from the app canvas up to cards.">
                    <Surfaces />
                </Section>

                <Section
                    title="Text"
                    description="Three steps of emphasis. Drop a step for each level of importance, never skip to a raw color."
                >
                    <TextRamp />
                </Section>

                <Section
                    title="Brand"
                    description="Follows the theme's primary hue. Use it for the one action that matters most on a screen."
                >
                    <Brand />
                </Section>

                <Section
                    title="Status"
                    description={
                        <>
                            Quill status tokens work the opposite way to shadcn. The bare name is a pale fill; text,
                            icons and strokes use the <Code>-foreground</Code> token. Bare text classes such as{' '}
                            <Code>text-destructive</Code> fail contrast, and the{' '}
                            <Code>quill-status-text-needs-foreground</Code> semgrep rule blocks them in CI.
                        </>
                    }
                >
                    <Status />
                </Section>

                <Section title="Lines" description="Edges and focus. Inputs get a stronger edge than static borders.">
                    <Lines />
                </Section>

                <Section
                    title="Interactive fills"
                    description="Overlays mixed from the foreground, so hover and selection read the same on any surface."
                >
                    <Fills />
                </Section>
            </div>
        )
    },
}
