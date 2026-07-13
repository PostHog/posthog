import {
    IconBolt,
    IconBrain,
    IconBug,
    IconCompass,
    IconDatabase,
    IconGithub,
    IconHeartPlus,
    IconList,
    IconRewindPlay,
    IconStack,
    IconSupport,
    IconReceipt,
} from '@posthog/icons'

import { SignalSourceProduct } from '../../types'

interface SourceProductMeta {
    Icon: typeof IconBolt
    /** CSS color value applied to the icon. */
    color: string
    label: string
}

/**
 * Shared source-product metadata used across inbox cards. Keyed on
 * `SignalSourceProduct` so a typo'd lookup fails to compile rather than
 * silently returning undefined at runtime.
 *
 * `Partial` because the backend may ship a new source product before the
 * renderer learns about it – callers must handle the `undefined` case via
 * `getSourceProductMeta`, which returns `null` for unknown keys.
 */
export const SOURCE_PRODUCT_META: Partial<Record<SignalSourceProduct, SourceProductMeta>> = {
    [SignalSourceProduct.SessionReplay]: {
        Icon: IconRewindPlay,
        color: 'var(--warning)',
        label: 'Session replay',
    },
    [SignalSourceProduct.ErrorTracking]: {
        Icon: IconBug,
        color: 'var(--danger)',
        label: 'Error tracking',
    },
    [SignalSourceProduct.LlmAnalytics]: {
        Icon: IconBrain,
        color: 'var(--purple)',
        label: 'AI observability',
    },
    [SignalSourceProduct.Github]: {
        Icon: IconGithub,
        color: 'var(--text-secondary)',
        label: 'GitHub',
    },
    [SignalSourceProduct.Linear]: {
        Icon: IconStack,
        color: 'var(--blue)',
        label: 'Linear',
    },
    [SignalSourceProduct.Zendesk]: {
        Icon: IconReceipt,
        color: 'var(--success)',
        label: 'Zendesk',
    },
    [SignalSourceProduct.Conversations]: {
        Icon: IconSupport,
        color: 'var(--blue)',
        label: 'Conversations',
    },
    [SignalSourceProduct.Pganalyze]: {
        Icon: IconDatabase,
        color: 'var(--text-primary)',
        label: 'pganalyze',
    },
    [SignalSourceProduct.SignalsScout]: {
        Icon: IconCompass,
        color: 'var(--purple)',
        label: 'Scout',
    },
    [SignalSourceProduct.Endpoints]: {
        Icon: IconBolt,
        color: 'var(--warning)',
        label: 'Endpoints',
    },
    [SignalSourceProduct.Logs]: {
        Icon: IconList,
        color: 'var(--text-secondary)',
        label: 'Logs',
    },
    [SignalSourceProduct.HealthChecks]: {
        Icon: IconHeartPlus,
        color: 'var(--danger)',
        label: 'Health checks',
    },
}

/**
 * Lookup helper accepting the loosely-typed `source_products` strings from the
 * backend. Returns metadata only for recognized keys, else `null`.
 */
export function getSourceProductMeta(value: string | null | undefined): SourceProductMeta | null {
    if (!value) {
        return null
    }
    return SOURCE_PRODUCT_META[value as SignalSourceProduct] ?? null
}

/** True if at least one source product in `values` has known display metadata. */
export function hasKnownSourceProduct(values: string[] | null | undefined): boolean {
    return (values ?? []).some((value) => getSourceProductMeta(value) !== null)
}

export interface KnownSourceProductEntry {
    key: string
    meta: SourceProductMeta
}

/** Resolve `source_products` strings to entries with known display metadata, preserving order. */
export function knownSourceProductEntries(sourceProducts: string[] | null | undefined): KnownSourceProductEntry[] {
    return (sourceProducts ?? [])
        .map((key) => ({ key, meta: getSourceProductMeta(key) }))
        .filter((entry): entry is KnownSourceProductEntry => entry.meta !== null)
}

/** Tooltip copy listing every contributing source product, shared by the card and detail meta rows. */
export function sourceProductsTooltipTitle(entries: KnownSourceProductEntry[]): string {
    return `Signals in this report came from: ${entries.map((e) => e.meta.label).join(', ')}`
}

/** Row of color-coded source-product icons. Surfaces vary in wrapper layout, so the caller supplies `className`. */
export function SourceProductIconRow({
    entries,
    className,
}: {
    entries: KnownSourceProductEntry[]
    className?: string
}): JSX.Element {
    return (
        <span className={className}>
            {entries.map((entry) => {
                const Icon = entry.meta.Icon
                return (
                    <span
                        key={entry.key}
                        className="inline-flex shrink-0 items-center"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: entry.meta.color }}
                        aria-hidden
                    >
                        <Icon className="text-xs" />
                    </span>
                )
            })}
        </span>
    )
}
