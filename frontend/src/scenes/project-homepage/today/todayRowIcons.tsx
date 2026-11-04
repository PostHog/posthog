import {
    IconBell,
    IconDatabase,
    IconDecisionTree,
    IconFlask,
    IconMessage,
    IconRewindPlay,
    IconSupport,
    IconToggle,
    IconTrends,
    IconWarning,
} from '@posthog/icons'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { HighlightItemApi } from 'products/today/frontend/generated/api.schemas'

import { TodayIcon } from './TodayIcon'
import { sourceStyle } from './todaySignalReports'

export interface TodayRowIcon {
    color?: string
    glyph: JSX.Element
}

const ANALYTICS: TodayRowIcon = {
    color: 'var(--color-product-product-analytics-light)',
    glyph: <IconTrends />,
}

const REPLAY: TodayRowIcon = { color: 'var(--color-product-session-replay-light)', glyph: <IconRewindPlay /> }

const PRODUCT_ICONS: Record<string, TodayRowIcon> = {
    alerts: { color: 'var(--color-product-alerts-light)', glyph: <IconBell /> },
    conversations: { color: 'var(--color-product-support-light)', glyph: <IconSupport /> },
    error_tracking: { color: 'var(--color-product-error-tracking-light)', glyph: <IconWarning /> },
    experiments: { color: 'var(--color-product-experiments-light)', glyph: <IconFlask /> },
    feature_flags: { color: 'var(--color-product-feature-flags-light)', glyph: <IconToggle /> },
    replay: REPLAY,
    surveys: { color: 'var(--color-product-surveys-light)', glyph: <IconMessage /> },
    warehouse_sources: { color: 'var(--color-product-data-warehouse-light)', glyph: <IconDatabase /> },
    warehouse_suggestions: { color: 'var(--color-product-data-warehouse-light)', glyph: <IconDatabase /> },
    workflows: { color: 'var(--color-product-workflows-light)', glyph: <IconDecisionTree /> },
}

// Rage clicks come from web analytics, but the row opens the recordings.
const SOURCE_ICONS: Record<string, TodayRowIcon> = {
    rage: REPLAY,
}

function sourceIcon(source: string | null | undefined): TodayRowIcon {
    const style = sourceStyle(source)
    const colored = style.color.startsWith('var(--color-product-')
    return { color: colored ? style.color : undefined, glyph: <TodayIcon icon={style.icon} /> }
}

export function reportIcon(report: Pick<SignalReport, 'source_products'>): TodayRowIcon {
    return sourceIcon(report.source_products?.[0])
}

export function highlightIcon(item: Pick<HighlightItemApi, 'source' | 'product'>): TodayRowIcon {
    return SOURCE_ICONS[item.source] ?? (item.product ? PRODUCT_ICONS[item.product] : undefined) ?? ANALYTICS
}
