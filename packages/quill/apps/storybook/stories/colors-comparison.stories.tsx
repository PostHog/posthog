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
    // ── Input fills ─────────────────────────────────────
    'bg-fill-input': { light: '#fff', dark: 'hsl(240 8% 10%)' },
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

type Verdict = 'KEEP' | 'KILLED' | 'ADD' | 'RENAME' | 'DECIDE'
type Row = {
    label: string
    note?: string
    quill?: { token: string; light: string; dark: string }
    posthog?: { token: string; light: string; dark: string }
    verdict: Verdict
    recommendation: string
}

const VERDICT_STYLE: Record<Verdict, string> = {
    KEEP: 'bg-success text-success-foreground',
    KILLED: 'bg-destructive text-destructive-foreground',
    ADD: 'bg-info text-info-foreground',
    RENAME: 'bg-warning text-warning-foreground',
    DECIDE: 'bg-muted text-muted-foreground',
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
        verdict: 'KEEP',
        recommendation: 'Direct drop-in. Quill light is slightly cooler than PostHog warm yellowish — within tolerance.',
    },
    {
        label: 'Primary surface (cards, modals, tables)',
        quill: quillRow('card'),
        posthog: phRow('bg-surface-primary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in. Both effectively white in light mode.',
    },
    {
        label: 'Secondary surface (subdued cards, list rows)',
        quill: quillRow('muted'),
        posthog: phRow('bg-surface-secondary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in. Use `bg-muted` wherever PostHog says `bg-surface-secondary`.',
    },
    {
        label: 'Tertiary surface (toolbars)',
        posthog: phRow('bg-surface-tertiary'),
        verdict: 'DECIDE',
        recommendation:
            "Don't add yet. Quill has no toolbar primitive that needs a 3rd surface tier. Revisit if/when one lands.",
    },
    {
        label: 'Popover surface',
        verdict: 'KILLED',
        recommendation: 'Folded into `card`. All consumers (popover, combobox, select, menus, command, toast, date-time-picker) now use `var(--card)` + `var(--foreground)`.',
    },
    {
        label: 'Hover/focus surface (shadcn-style "accent")',
        verdict: 'KILLED',
        recommendation:
            'Replaced by `fill-hover` (hover/focus) and `fill-selected` (open/range). Surface uses (badge, skeleton, tabs) → `muted`; borders (checkbox, radio) → `border`.',
    },
    // ── Text ────────────────────────────────────────────
    {
        label: 'Primary text',
        quill: quillRow('foreground'),
        posthog: phRow('text-primary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'De-emphasized text',
        quill: quillRow('muted-foreground'),
        posthog: phRow('text-secondary'),
        verdict: 'KEEP',
        recommendation:
            'Drop-in. Quill light is slightly lower lightness — still passes contrast on muted bg. Re-check after surface alignment.',
    },
    {
        label: 'Tertiary text',
        posthog: phRow('text-tertiary'),
        verdict: 'DECIDE',
        recommendation:
            'Skip. 2 text tiers is enough; PostHog rarely uses tertiary. Add only if a primitive demands a 3rd weight.',
    },
    // ── Brand ───────────────────────────────────────────
    {
        label: 'Brand color',
        quill: quillRow('primary'),
        posthog: phRow('accent'),
        verdict: 'KEEP',
        recommendation:
            "Keep `primary` name (shadcn portability > PostHog naming alignment). Brand surface area is small — translation cost is manageable. Document the alias in tokens README: 'quill `primary` ≡ PostHog `--color-accent`'.",
    },
    {
        label: 'Brand foreground',
        quill: quillRow('primary-foreground'),
        verdict: 'KEEP',
        recommendation:
            'Keep. PostHog has no exposed token; quill needs explicit contrast on brand bg. Same colour PostHog hardcodes (white in light, dark in dark).',
    },
    {
        label: 'Secondary button (dark grey)',
        verdict: 'KILLED',
        recommendation: 'No active consumers — only `item.css` referenced `--secondary` for a pressable hover border, swapped to `--border`.',
    },
    // ── Status: backgrounds ─────────────────────────────
    {
        label: 'Destructive bg',
        quill: quillRow('destructive'),
        posthog: phRow('bg-fill-error-secondary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in. Both use ~red-100/red-900 equivalents.',
    },
    {
        label: 'Success bg',
        quill: quillRow('success'),
        posthog: phRow('bg-fill-success-secondary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'Warning bg',
        quill: quillRow('warning'),
        posthog: phRow('bg-fill-warning-secondary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'Info bg',
        quill: quillRow('info'),
        posthog: phRow('bg-fill-info-secondary'),
        verdict: 'KEEP',
        recommendation:
            'Drop-in. Note quill dark uses 40% alpha; PostHog uses solid blue-950. Tweak quill dark to solid if range highlights look washed.',
    },
    // ── Status: foregrounds ─────────────────────────────
    {
        label: 'Destructive text',
        quill: quillRow('destructive-foreground'),
        posthog: phRow('text-error'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'Success text',
        quill: quillRow('success-foreground'),
        posthog: phRow('text-success'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'Warning text',
        quill: quillRow('warning-foreground'),
        posthog: phRow('text-warning'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'Info text',
        quill: quillRow('info-foreground'),
        verdict: 'KEEP',
        recommendation: 'Keep. PostHog has no `--color-text-info`; quill fills the gap.',
    },
    // ── Borders & rings ─────────────────────────────────
    {
        label: 'Default border',
        quill: quillRow('border'),
        posthog: phRow('border-primary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in.',
    },
    {
        label: 'Input border',
        quill: quillRow('input'),
        posthog: phRow('border-secondary'),
        verdict: 'KEEP',
        recommendation: 'Drop-in. Both intentionally darker than default border for input affordance.',
    },
    {
        label: 'Focus ring',
        quill: quillRow('ring'),
        verdict: 'DECIDE',
        recommendation:
            'PostHog uses `--color-accent` (brand) for focus rings — quill uses neutral grey. Consider repointing quill `ring` to `var(--primary)` to match PostHog feel. Visual test required.',
    },
    // ── Interactive fills ───────────────────────────────
    {
        label: 'Hover fill',
        quill: quillRow('fill-hover'),
        posthog: phRow('bg-fill-button-tertiary-hover'),
        verdict: 'KEEP',
        recommendation:
            "Quill's relative-mix on `--foreground` is *better* than PostHog's fixed black/white mix — works on any surface. PostHog should adopt this pattern, not the other way around.",
    },
    {
        label: 'Selected fill',
        quill: quillRow('fill-selected'),
        posthog: phRow('bg-fill-button-tertiary-active'),
        verdict: 'KEEP',
        recommendation: 'Same as hover — keep quill pattern.',
    },
    {
        label: 'Expanded fill',
        quill: quillRow('fill-expanded'),
        posthog: phRow('bg-fill-button-panel-active'),
        verdict: 'KEEP',
        recommendation: 'Same.',
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

function VerdictPill({ verdict }: { verdict: Verdict }): React.ReactElement {
    return (
        <span
            className={`inline-block px-1.5 py-0.5 text-[10px] font-mono font-bold rounded-xs uppercase tracking-wide w-fit ${VERDICT_STYLE[verdict]}`}
        >
            {verdict}
        </span>
    )
}

function ComparisonRow({ row }: { row: Row }): React.ReactElement {
    return (
        <div className="grid grid-cols-[220px_180px_180px_1fr] gap-4 items-start py-3 border-b border-border/40">
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

            <div className="flex flex-col gap-1.5">
                <VerdictPill verdict={row.verdict} />
                <span className="text-xs text-foreground leading-snug">{row.recommendation}</span>
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
                <p className="text-xs text-muted-foreground">
                    Goal: make quill a near drop-in for PostHog. Small variance is OK; large variance flags a kill or
                    realign candidate.
                </p>
                <div className="flex gap-3 flex-wrap pt-2">
                    {(Object.keys(VERDICT_STYLE) as Verdict[]).map((v) => (
                        <VerdictPill key={v} verdict={v} />
                    ))}
                </div>
            </div>

            <div className="grid grid-cols-[220px_180px_180px_1fr] gap-4 pb-2 border-b border-border text-xs font-mono uppercase tracking-wide text-muted-foreground">
                <span>Purpose</span>
                <span>Quill (light / dark)</span>
                <span>PostHog (light / dark)</span>
                <span>Recommendation</span>
            </div>

            <div>
                {rows.map((row) => (
                    <ComparisonRow key={row.label} row={row} />
                ))}
            </div>
        </div>
    ),
}
