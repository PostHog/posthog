import {
    IconBolt,
    IconBrain,
    IconBug,
    IconCompass,
    IconDatabase,
    IconGithub,
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
    [SignalSourceProduct.SESSION_REPLAY]: {
        Icon: IconRewindPlay,
        color: 'var(--warning)',
        label: 'Session replay',
    },
    [SignalSourceProduct.ERROR_TRACKING]: {
        Icon: IconBug,
        color: 'var(--danger)',
        label: 'Error tracking',
    },
    [SignalSourceProduct.LLM_ANALYTICS]: {
        Icon: IconBrain,
        color: 'var(--purple)',
        label: 'AI observability',
    },
    [SignalSourceProduct.GITHUB]: {
        Icon: IconGithub,
        color: 'var(--text-secondary)',
        label: 'GitHub',
    },
    [SignalSourceProduct.LINEAR]: {
        Icon: IconStack,
        color: 'var(--blue)',
        label: 'Linear',
    },
    [SignalSourceProduct.ZENDESK]: {
        Icon: IconReceipt,
        color: 'var(--success)',
        label: 'Zendesk',
    },
    [SignalSourceProduct.CONVERSATIONS]: {
        Icon: IconSupport,
        color: 'var(--blue)',
        label: 'Conversations',
    },
    [SignalSourceProduct.PGANALYZE]: {
        Icon: IconDatabase,
        color: 'var(--text-primary)',
        label: 'pganalyze',
    },
    [SignalSourceProduct.SIGNALS_SCOUT]: {
        Icon: IconCompass,
        color: 'var(--purple)',
        label: 'Scout',
    },
    [SignalSourceProduct.ENDPOINTS]: {
        Icon: IconBolt,
        color: 'var(--warning)',
        label: 'Endpoints',
    },
    [SignalSourceProduct.LOGS]: {
        Icon: IconList,
        color: 'var(--text-secondary)',
        label: 'Logs',
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
