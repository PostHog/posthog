import { type ProductKey } from '~/queries/schema/schema-general'

export interface MetricCard {
    label: string
    value: string
    /** e.g. "12.4%" — rendered with a direction arrow. */
    delta?: string
    deltaPositive?: boolean
}

/**
 * The swappable center of the preview. Add a new page by extending this union and handling it in
 * `pages/index.tsx` (PreviewPageView) — the chrome and presets stay untouched.
 */
export type PreviewPage =
    | { kind: 'empty'; title?: string; subtitle?: string }
    | { kind: 'dashboard'; metrics: MetricCard[]; showTrend?: boolean; showBars?: boolean }

export interface SidebarConfig {
    /** Products listed in the nav, in order. */
    products: ProductKey[]
    /** Highlighted nav item; defaults to the first product. */
    activeProductKey?: ProductKey | null
}

/** Fully describes one preview frame: org identity, sidebar, and the active page. */
export interface PreviewConfig {
    org: { name: string; logoUrl?: string | null }
    sidebar: SidebarConfig
    page: PreviewPage
}
