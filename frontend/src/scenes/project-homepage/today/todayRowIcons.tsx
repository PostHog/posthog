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

const WORKFLOWS: TodayRowIcon = { color: 'var(--color-product-workflows-light)', glyph: <IconDecisionTree /> }

const HIGHLIGHT_ICONS: Record<string, TodayRowIcon> = {
    alerts: { color: 'var(--color-product-alerts-light)', glyph: <IconBell /> },
    errors: { color: 'var(--color-product-error-tracking-light)', glyph: <IconWarning /> },
    experiments: { color: 'var(--color-product-experiments-light)', glyph: <IconFlask /> },
    flags: { color: 'var(--color-product-feature-flags-light)', glyph: <IconToggle /> },
    rage: { color: 'var(--color-product-session-replay-light)', glyph: <IconRewindPlay /> },
    surveys: { color: 'var(--color-product-surveys-light)', glyph: <IconMessage /> },
    ticket_sla: { color: 'var(--color-product-support-light)', glyph: <IconSupport /> },
    warehouse_syncs: { color: 'var(--color-product-data-warehouse-light)', glyph: <IconDatabase /> },
    workflow_ideas: WORKFLOWS,
    workflows: WORKFLOWS,
}

function sourceIcon(source: string | null | undefined): TodayRowIcon {
    const style = sourceStyle(source)
    const colored = style.color.startsWith('var(--color-product-')
    return { color: colored ? style.color : undefined, glyph: <TodayIcon icon={style.icon} /> }
}

export function reportIcon(report: Pick<SignalReport, 'source_products'>): TodayRowIcon {
    return sourceIcon(report.source_products?.[0])
}

export function highlightIcon(item: Pick<HighlightItemApi, 'source'>): TodayRowIcon {
    return HIGHLIGHT_ICONS[item.source] ?? ANALYTICS
}
