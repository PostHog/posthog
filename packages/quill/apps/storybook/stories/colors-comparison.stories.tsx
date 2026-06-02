import type { Meta, StoryObj } from '@storybook/react'

import { semanticColors } from '@posthog/quill-tokens'

const meta = {
    title: 'Tokens/Colors Comparison',
    tags: ['autodocs'],
} satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

/**
 * PostHog color values — sourced from `frontend/src/styles/base.scss`.
 * Hardcoded as static values so this story renders without loading
 * PostHog's stylesheet. Update if `base.scss` changes.
 */
type PhValue = { light: string; dark: string }
const ph: Record<string, PhValue> = {
    // ── Backgrounds ────────────────────────────────────
    'bg-primary': { light: 'hsl(75 14% 95%)', dark: 'hsl(240 8% 8%)' },
    'bg-surface-primary': { light: '#fff', dark: 'hsl(235 8% 15%)' },
    'bg-surface-secondary': { light: 'hsl(70 16% 93%)', dark: 'hsl(240 8% 10%)' },
    'bg-surface-tertiary': { light: 'hsl(77 13% 89%)', dark: 'hsl(240 8% 8%)' },
    // ── Text ────────────────────────────────────────────
    'text-primary': { light: 'hsl(0 0% 5%)', dark: 'hsl(0 0% 90%)' },
    'text-secondary': { light: 'hsl(0 0% 25%)', dark: 'hsl(0 0% 65%)' },
    'text-tertiary': { light: 'hsl(0 0% 40%)', dark: 'hsl(0 0% 60%)' },
    // ── Brand ───────────────────────────────────────────
    accent: { light: 'hsl(19 100% 48%)', dark: 'hsl(43 94% 57%)' },
    // ── Status fills (secondary) ────────────────────────
    'bg-fill-error-secondary': {
        light: 'oklch(0.936 0.032 17.717deg)',
        dark: 'oklch(0.258 0.092 26.042deg)',
    },
    'bg-fill-success-secondary': {
        light: 'oklch(0.962 0.044 156.743deg)',
        dark: 'oklch(0.266 0.065 152.934deg)',
    },
    'bg-fill-warning-secondary': {
        light: 'oklch(0.973 0.071 103.193deg)',
        dark: 'oklch(0.286 0.066 53.813deg)',
    },
    'bg-fill-info-secondary': {
        light: 'oklch(0.932 0.032 255.585deg)',
        dark: 'oklch(0.282 0.091 267.935deg)',
    },
    // ── Status text ─────────────────────────────────────
    'text-error': { light: 'oklch(0.577 0.245 27.325deg)', dark: 'oklch(0.704 0.191 22.216deg)' },
    'text-success': { light: 'oklch(0.627 0.194 149.214deg)', dark: 'oklch(0.792 0.209 151.711deg)' },
    'text-warning': { light: 'oklch(0.554 0.135 66.442deg)', dark: 'oklch(0.852 0.199 91.936deg)' },
    // ── Borders ─────────────────────────────────────────
    'border-primary': { light: 'hsl(78 13% 85%)', dark: 'hsl(230 8% 20%)' },
    'border-secondary': { light: 'hsl(69 8% 65%)', dark: 'hsl(230 8% 40%)' },
    // ── Hover/active fills (relative-mix on black/white) ─
    'bg-fill-button-tertiary-hover': {
        light: 'color-mix(in oklab, #000 7.5%, transparent)',
        dark: 'color-mix(in oklab, #fff 7.5%, transparent)',
    },
    'bg-fill-button-tertiary-active': {
        light: 'color-mix(in oklab, #000 5%, transparent)',
        dark: 'color-mix(in oklab, #fff 5%, transparent)',
    },
    'bg-fill-button-panel-active': {
        light: 'color-mix(in oklab, #000 7.5%, transparent)',
        dark: 'color-mix(in oklab, #fff 7.5%, transparent)',
    },
}

type Row = {
    label: string
    note?: string
    quill?: { token: string; light: string; dark: string }
    posthog?: { token: string; light: string; dark: string }
}

function quillRow(token: keyof typeof semanticColors): Row['quill'] {
    const tuple = semanticColors[token]
    return { token, light: tuple[0], dark: tuple[1] }
}
function phRow(name: keyof typeof ph): Row['posthog'] {
    return { token: `--color-${name}`, light: ph[name].light, dark: ph[name].dark }
}

const rows: Row[] = [
    // ── Surfaces ────────────────────────────────────────
    {
        label: 'App background (shell behind surfaces)',
        quill: quillRow('background'),
        posthog: phRow('bg-primary'),
    },
    {
        label: 'Primary surface (cards, modals, tables)',
        quill: quillRow('card'),
        posthog: phRow('bg-surface-primary'),
    },
    {
        label: 'Secondary surface (subdued cards, list rows)',
        quill: quillRow('muted'),
        posthog: phRow('bg-surface-secondary'),
    },
    {
        label: 'Tertiary surface (toolbars, menubars, nav chrome)',
        quill: quillRow('chrome'),
        posthog: phRow('bg-surface-tertiary'),
    },
    // ── Text ────────────────────────────────────────────
    {
        label: 'Primary text',
        quill: quillRow('foreground'),
        posthog: phRow('text-primary'),
    },
    {
        label: 'De-emphasized text',
        quill: quillRow('muted-foreground'),
        posthog: phRow('text-secondary'),
    },
    {
        label: 'Tertiary text',
        posthog: phRow('text-tertiary'),
    },
    // ── Brand ───────────────────────────────────────────
    {
        label: 'Brand color',
        quill: quillRow('primary'),
        posthog: phRow('accent'),
    },
    {
        label: 'Brand foreground',
        quill: quillRow('primary-foreground'),
    },
    // ── Status: backgrounds ─────────────────────────────
    {
        label: 'Destructive bg',
        quill: quillRow('destructive'),
        posthog: phRow('bg-fill-error-secondary'),
    },
    {
        label: 'Success bg',
        quill: quillRow('success'),
        posthog: phRow('bg-fill-success-secondary'),
    },
    {
        label: 'Warning bg',
        quill: quillRow('warning'),
        posthog: phRow('bg-fill-warning-secondary'),
    },
    {
        label: 'Info bg',
        quill: quillRow('info'),
        posthog: phRow('bg-fill-info-secondary'),
    },
    // ── Status: foregrounds ─────────────────────────────
    {
        label: 'Destructive text',
        quill: quillRow('destructive-foreground'),
        posthog: phRow('text-error'),
    },
    {
        label: 'Success text',
        quill: quillRow('success-foreground'),
        posthog: phRow('text-success'),
    },
    {
        label: 'Warning text',
        quill: quillRow('warning-foreground'),
        posthog: phRow('text-warning'),
    },
    {
        label: 'Info text',
        quill: quillRow('info-foreground'),
    },
    // ── Borders & rings ─────────────────────────────────
    {
        label: 'Default border',
        quill: quillRow('border'),
        posthog: phRow('border-primary'),
    },
    {
        label: 'Input border',
        quill: quillRow('input'),
        posthog: phRow('border-secondary'),
    },
    {
        label: 'Focus ring',
        quill: quillRow('ring'),
    },
    // ── Interactive fills ───────────────────────────────
    {
        label: 'Hover fill',
        quill: quillRow('fill-hover'),
        posthog: phRow('bg-fill-button-tertiary-hover'),
    },
    {
        label: 'Selected fill',
        quill: quillRow('fill-selected'),
        posthog: phRow('bg-fill-button-tertiary-active'),
    },
    {
        label: 'Expanded fill',
        quill: quillRow('fill-expanded'),
        posthog: phRow('bg-fill-button-panel-active'),
    },
]

function Swatch({ value }: { value: string }): React.ReactElement {
    return (
        <div
            className="size-12 rounded-sm border border-border shrink-0"
            style={{ backgroundColor: value }}
            title={value}
        />
    )
}

function EmptyCell(): React.ReactElement {
    return (
        <div className="flex gap-1">
            <div className="size-12 rounded-sm border border-dashed border-border/60 shrink-0 grid place-items-center text-[10px] text-muted-foreground">
                —
            </div>
            <div className="size-12 rounded-sm border border-dashed border-border/60 shrink-0 grid place-items-center text-[10px] text-muted-foreground">
                —
            </div>
        </div>
    )
}

function SidePair({ light, dark }: { light: string; dark: string }): React.ReactElement {
    return (
        <div className="flex gap-1">
            <Swatch value={light} />
            <Swatch value={dark} />
        </div>
    )
}

function ComparisonRow({ row }: { row: Row }): React.ReactElement {
    return (
        <div className="grid grid-cols-[260px_1fr_1fr] gap-4 items-start py-3 border-b border-border/40">
            <div className="flex flex-col gap-1">
                <span className="text-sm font-medium">{row.label}</span>
                {row.note && <span className="text-xs text-muted-foreground">{row.note}</span>}
            </div>

            <div className="flex flex-col gap-1">
                {row.quill ? (
                    <>
                        <SidePair light={row.quill.light} dark={row.quill.dark} />
                        <span className="text-xs text-muted-foreground font-mono">{row.quill.token}</span>
                    </>
                ) : (
                    <EmptyCell />
                )}
            </div>

            <div className="flex flex-col gap-1">
                {row.posthog ? (
                    <>
                        <SidePair light={row.posthog.light} dark={row.posthog.dark} />
                        <span className="text-xs text-muted-foreground font-mono">{row.posthog.token}</span>
                    </>
                ) : (
                    <EmptyCell />
                )}
            </div>
        </div>
    )
}

export const QuillVsPostHog: Story = {
    render: () => (
        <div className="space-y-4 max-w-7xl">
            <div className="space-y-1">
                <h2 className="text-base font-semibold">Quill vs PostHog color tokens</h2>
                <p className="text-sm text-muted-foreground">
                    Side-by-side comparison of quill semantic tokens and their PostHog `base.scss` equivalents. Each
                    pair shows light then dark. Empty cells mean no direct equivalent on that side.
                </p>
            </div>

            <div className="grid grid-cols-[260px_1fr_1fr] gap-4 pb-2 border-b border-border text-xs font-mono uppercase tracking-wide text-muted-foreground">
                <span>Purpose</span>
                <span>Quill (light / dark)</span>
                <span>PostHog (light / dark)</span>
            </div>

            <div>
                {rows.map((row) => (
                    <ComparisonRow key={row.label} row={row} />
                ))}
            </div>
        </div>
    ),
}
