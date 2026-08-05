import {
    IconBolt,
    IconBrain,
    IconBug,
    IconCompass,
    IconDatabase,
    IconEye,
    IconGear,
    IconGithub,
    IconGraph,
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
    colorClass: string
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
        colorClass: 'text-warning',
        label: 'Session replay',
    },
    [SignalSourceProduct.ReplayVision]: {
        Icon: IconEye,
        colorClass: 'text-warning',
        label: 'Replay vision',
    },
    [SignalSourceProduct.ErrorTracking]: {
        Icon: IconBug,
        colorClass: 'text-danger',
        label: 'Error tracking',
    },
    [SignalSourceProduct.LlmAnalytics]: {
        Icon: IconBrain,
        colorClass: 'text-accent',
        label: 'AI observability',
    },
    [SignalSourceProduct.Github]: {
        Icon: IconGithub,
        colorClass: 'text-secondary',
        label: 'GitHub',
    },
    [SignalSourceProduct.Linear]: {
        Icon: IconStack,
        colorClass: 'text-accent',
        label: 'Linear',
    },
    [SignalSourceProduct.Zendesk]: {
        Icon: IconReceipt,
        colorClass: 'text-success',
        label: 'Zendesk',
    },
    [SignalSourceProduct.Conversations]: {
        Icon: IconSupport,
        colorClass: 'text-accent',
        label: 'Support',
    },
    [SignalSourceProduct.Pganalyze]: {
        Icon: IconDatabase,
        colorClass: 'text-primary',
        label: 'pganalyze',
    },
    [SignalSourceProduct.SignalsScout]: {
        Icon: IconCompass,
        colorClass: 'text-accent',
        label: 'Scout',
    },
    [SignalSourceProduct.Endpoints]: {
        Icon: IconBolt,
        colorClass: 'text-warning',
        label: 'Endpoints',
    },
    [SignalSourceProduct.Logs]: {
        Icon: IconList,
        colorClass: 'text-secondary',
        label: 'Logs',
    },
    [SignalSourceProduct.HealthChecks]: {
        Icon: IconHeartPlus,
        colorClass: 'text-danger',
        label: 'Health checks',
    },
    [SignalSourceProduct.EngineeringAnalytics]: {
        Icon: IconGear,
        colorClass: 'text-warning',
        label: 'Engineering analytics',
    },
    [SignalSourceProduct.Analytics]: {
        Icon: IconGraph,
        colorClass: 'text-accent',
        label: 'Product analytics',
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
                    <span key={entry.key} className="inline-flex shrink-0 items-center" aria-hidden>
                        <Icon className={`text-xs ${entry.meta.colorClass}`} />
                    </span>
                )
            })}
        </span>
    )
}
