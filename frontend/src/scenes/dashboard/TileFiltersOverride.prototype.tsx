// scenes/dashboard/TileFiltersOverride.prototype.tsx
//
// THROWAWAY PROTOTYPE — do not fold into production as-is.
// Question: how should the "Override tile filters" modal section its controls?
// Renders five structurally different sectionings of the same wired controls,
// switchable via `?tileOverrideVariant=` and a dev-only floating bottom bar.
// Winner gets hand-folded into TileFiltersOverride.tsx; this file + the switcher get deleted.
// See `/prototype` (UI.md).

import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonCard, LemonCollapse, LemonDivider } from '@posthog/lemon-ui'

// The wired control blocks, built once in TileFiltersOverride.tsx and arranged differently per variant.
export type TileOverrideFields = Record<
    'scope' | 'dateRange' | 'interval' | 'properties' | 'testAccounts' | 'breakdown',
    JSX.Element
>

type Group = { heading: string; fields: JSX.Element[] }

// Same grouping for every variant — only the sectioning chrome around the groups changes.
function groupsOf(fields: TileOverrideFields): Group[] {
    return [
        { heading: 'Scope', fields: [fields.scope] },
        { heading: 'Time', fields: [fields.dateRange, fields.interval] },
        { heading: 'Filters', fields: [fields.properties, fields.testAccounts] },
        { heading: 'Display', fields: [fields.breakdown] },
    ]
}

const VARIANTS = [
    { key: 'A', name: 'Plain dividers' },
    { key: 'B', name: 'Labeled dividers' },
    { key: 'C', name: 'Group headings' },
    { key: 'D', name: 'Bordered cards' },
    { key: 'E', name: 'Collapse accordion' },
] as const

type VariantKey = (typeof VARIANTS)[number]['key']
const VARIANT_KEYS = VARIANTS.map((v) => v.key) as VariantKey[]

function GroupHeading({ children }: { children: string }): JSX.Element {
    return <h5 className="text-xs font-semibold text-muted uppercase mb-2 mt-0">{children}</h5>
}

// A — plain dividers between groups (today's production layout).
function VariantPlainDividers({ groups }: { groups: Group[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            {groups.map((group, i) => (
                <div key={group.heading} className="flex flex-col gap-4">
                    {i > 0 && <LemonDivider />}
                    {group.fields}
                </div>
            ))}
        </div>
    )
}

// B — dividers carry the group name in the line itself.
function VariantLabeledDividers({ groups }: { groups: Group[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            {groups.map((group) => (
                <div key={group.heading} className="flex flex-col gap-4">
                    <LemonDivider label={group.heading} />
                    {group.fields}
                </div>
            ))}
        </div>
    )
}

// C — small left-aligned heading above each group, no hairlines.
function VariantGroupHeadings({ groups }: { groups: Group[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-5">
            {groups.map((group) => (
                <div key={group.heading} className="flex flex-col gap-3">
                    <GroupHeading>{group.heading}</GroupHeading>
                    {group.fields}
                </div>
            ))}
        </div>
    )
}

// D — each group in its own bordered card.
function VariantBorderedCards({ groups }: { groups: Group[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {groups.map((group) => (
                <LemonCard key={group.heading} className="p-3" hoverEffect={false}>
                    <GroupHeading>{group.heading}</GroupHeading>
                    <div className="flex flex-col gap-4">{group.fields}</div>
                </LemonCard>
            ))}
        </div>
    )
}

// E — one collapsible panel per group.
function VariantCollapse({ groups }: { groups: Group[] }): JSX.Element {
    return (
        <LemonCollapse
            multiple
            defaultActiveKeys={groups.map((g) => g.heading)}
            panels={groups.map((group) => ({
                key: group.heading,
                header: group.heading,
                content: <div className="flex flex-col gap-4">{group.fields}</div>,
            }))}
        />
    )
}

function renderVariant(variant: VariantKey, groups: Group[]): JSX.Element {
    switch (variant) {
        case 'B':
            return <VariantLabeledDividers groups={groups} />
        case 'C':
            return <VariantGroupHeadings groups={groups} />
        case 'D':
            return <VariantBorderedCards groups={groups} />
        case 'E':
            return <VariantCollapse groups={groups} />
        case 'A':
        default:
            return <VariantPlainDividers groups={groups} />
    }
}

function isVariantKey(value: unknown): value is VariantKey {
    return typeof value === 'string' && (VARIANT_KEYS as string[]).includes(value)
}

// Dev-only floating bar: prev / label / next, plus ← → keys. Writes the URL so a variant is reload-stable.
function VariantSwitcher({ current }: { current: VariantKey }): JSX.Element {
    const { searchParams, location } = useValues(router)

    const go = (delta: number): void => {
        const idx = VARIANT_KEYS.indexOf(current)
        const next = VARIANT_KEYS[(idx + delta + VARIANT_KEYS.length) % VARIANT_KEYS.length]
        router.actions.replace(location.pathname, { ...searchParams, tileOverrideVariant: next })
    }

    useEffect(() => {
        const onKey = (e: KeyboardEvent): void => {
            const el = document.activeElement
            if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || (el as HTMLElement).isContentEditable)) {
                return
            }
            if (e.key === 'ArrowLeft') {
                go(-1)
            } else if (e.key === 'ArrowRight') {
                go(1)
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    })

    const name = VARIANTS.find((v) => v.key === current)?.name ?? ''

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[10000] flex items-center gap-2 rounded-full bg-black text-white px-3 py-1.5 shadow-lg pointer-events-auto">
            <button className="p-1 hover:opacity-70" onClick={() => go(-1)} aria-label="Previous variant">
                <IconChevronLeft />
            </button>
            <span className="text-xs font-semibold whitespace-nowrap">
                {current} — {name}
            </span>
            <button className="p-1 hover:opacity-70" onClick={() => go(1)} aria-label="Next variant">
                <IconChevronRight />
            </button>
        </div>
    )
}

// Prototype entry point rendered by TileFiltersOverride. In production it is always variant A with no switcher.
export function TileFiltersOverrideSections({ fields }: { fields: TileOverrideFields }): JSX.Element {
    const { searchParams } = useValues(router)
    const isProto = process.env.NODE_ENV !== 'production'
    const variant: VariantKey =
        isProto && isVariantKey(searchParams.tileOverrideVariant) ? searchParams.tileOverrideVariant : 'A'

    const groups = groupsOf(fields)

    return (
        <>
            {renderVariant(variant, groups)}
            {isProto && <VariantSwitcher current={variant} />}
        </>
    )
}
