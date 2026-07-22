import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCorrelationAnalysis, IconGraph } from '@posthog/icons'

import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightNavLogic } from 'scenes/insights/InsightNav/insightNavLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { INSIGHT_TYPES_METADATA, QUERY_TYPES_METADATA } from 'scenes/saved-insights/insightTypesMetadata'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, FunnelVizType, InsightType } from '~/types'

/**
 * THROWAWAY PROTOTYPE: variant E of the insight type switcher, see InsightTypeSwitcherPrototype.tsx.
 *
 * A type + view card that sits above the filters in the left editor sidebar, styled to stand
 * out from the filter sections below it: tinted accent card, an icon tile row for the type,
 * the selected type's name and description, and a "View as" subtype control where the type
 * has one (trends and stickiness: display, funnels: viz type).
 *
 * Lives in its own file so EditorFilters can import it without pulling in InsightsNav and the
 * saved-insights scene. Rendered from EditorFilters, but inert (null) unless the URL has
 * `?variant=sidebar`.
 */

export interface ExtraTypeEntry {
    key: string
    name: string
    description: string
    icon: React.ComponentType<any>
    tag: string
    disabledReason: string
}

export const CORE_TYPES: InsightType[] = [
    InsightType.TRENDS,
    InsightType.FUNNELS,
    InsightType.RETENTION,
    InsightType.PATHS,
    InsightType.STICKINESS,
    InsightType.LIFECYCLE,
]

export const EXTRA_TYPES: ExtraTypeEntry[] = [
    {
        key: 'CALENDAR_HEATMAP',
        name: 'Calendar heatmap',
        description: QUERY_TYPES_METADATA[NodeKind.CalendarHeatmapQuery].description ?? '',
        icon: QUERY_TYPES_METADATA[NodeKind.CalendarHeatmapQuery].icon,
        tag: 'Beta',
        disabledReason: 'Real query type without a tab slot today. Display-only in this prototype',
    },
    {
        key: 'SQL',
        name: 'SQL',
        description: INSIGHT_TYPES_METADATA[InsightType.SQL].description ?? '',
        icon: INSIGHT_TYPES_METADATA[InsightType.SQL].icon,
        tag: 'Editor',
        disabledReason: 'Would open the SQL editor. Display-only in this prototype',
    },
    {
        key: 'EXAMPLE_SANKEY',
        name: 'Sankey flow',
        description: 'Example future type, here to show how the list scales.',
        icon: IconGraph,
        tag: 'Example',
        disabledReason: 'Example future type. Display-only in this prototype',
    },
    {
        key: 'EXAMPLE_ANOMALY',
        name: 'Anomaly detection',
        description: 'Example future type, here to show how the list scales.',
        icon: IconCorrelationAnalysis,
        tag: 'Example',
        disabledReason: 'Example future type. Display-only in this prototype',
    },
]

interface SubtypeOption {
    value: string
    label: string
}

const TRENDS_VIEWS: SubtypeOption[] = [
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line' },
    { value: ChartDisplayType.ActionsBar, label: 'Bar' },
    { value: ChartDisplayType.BoldNumber, label: 'Number' },
    { value: ChartDisplayType.ActionsTable, label: 'Table' },
    { value: ChartDisplayType.ActionsPie, label: 'Pie' },
]

const STICKINESS_VIEWS: SubtypeOption[] = [
    { value: ChartDisplayType.ActionsLineGraph, label: 'Line' },
    { value: ChartDisplayType.ActionsBar, label: 'Bar' },
]

const FUNNEL_VIEWS: SubtypeOption[] = [
    { value: FunnelVizType.Steps, label: 'Steps' },
    { value: FunnelVizType.TimeToConvert, label: 'Time to convert' },
    { value: FunnelVizType.Trends, label: 'Trends' },
]

function TypeTile({
    name,
    icon: Icon,
    selected,
    onClick,
    disabledReason,
}: {
    name: string
    icon: React.ComponentType<any>
    selected: boolean
    onClick?: () => void
    disabledReason?: string
}): JSX.Element {
    return (
        <Tooltip title={disabledReason ? `${name}: ${disabledReason}` : name} placement="top">
            <button
                type="button"
                aria-pressed={selected}
                aria-label={name}
                onClick={disabledReason ? undefined : onClick}
                className={clsx(
                    'flex h-8 w-8 items-center justify-center rounded-md border text-base transition-colors',
                    selected
                        ? 'border-accent bg-surface-primary text-accent shadow-sm'
                        : 'text-secondary border-transparent',
                    disabledReason ? 'cursor-not-allowed opacity-40' : 'cursor-pointer',
                    !disabledReason && !selected && 'hover:bg-surface-primary hover:text-primary'
                )}
                data-attr={`prototype-insight-type-tile-${name.toLowerCase().replace(/\s+/g, '-')}`}
            >
                <Icon />
            </button>
        </Tooltip>
    )
}

/** Variant E: the type + view card above the filters in the left editor sidebar. */
export function SidebarTypeCardPrototype(): JSX.Element | null {
    const { searchParams } = useValues(router)
    const { insightProps } = useValues(insightLogic)
    const { activeView } = useValues(insightNavLogic(insightProps))
    const { setActiveView } = useActions(insightNavLogic(insightProps))
    const { display, funnelsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (searchParams.variant !== 'sidebar') {
        return null
    }

    const meta = INSIGHT_TYPES_METADATA[activeView] ?? INSIGHT_TYPES_METADATA[InsightType.TRENDS]

    let viewOptions: SubtypeOption[] | null = null
    let viewValue: string | null = null
    let onViewChange: ((value: string) => void) | null = null
    if (activeView === InsightType.TRENDS || activeView === InsightType.STICKINESS) {
        viewOptions = activeView === InsightType.TRENDS ? TRENDS_VIEWS : STICKINESS_VIEWS
        viewValue = (display as string | undefined) ?? ChartDisplayType.ActionsLineGraph
        onViewChange = (value) => updateInsightFilter({ display: value as ChartDisplayType })
    } else if (activeView === InsightType.FUNNELS) {
        viewOptions = FUNNEL_VIEWS
        viewValue = (funnelsFilter?.funnelVizType as string | undefined) ?? FunnelVizType.Steps
        onViewChange = (value) => updateInsightFilter({ funnelVizType: value as FunnelVizType })
    }

    return (
        <div
            className="border-accent bg-accent-highlight-secondary mb-3 rounded-lg border p-3"
            data-attr="prototype-insight-type-sidebar-card"
        >
            <div className="text-accent text-[0.625rem] font-semibold tracking-wide uppercase">Insight type</div>
            <div className="mt-2 flex flex-wrap gap-1">
                {CORE_TYPES.map((type) => (
                    <TypeTile
                        key={type}
                        name={INSIGHT_TYPES_METADATA[type].name}
                        icon={INSIGHT_TYPES_METADATA[type].icon}
                        selected={type === activeView}
                        onClick={() => setActiveView(type)}
                    />
                ))}
                <div className="border-accent mx-1 my-1 w-px self-stretch border-l opacity-40" />
                {EXTRA_TYPES.map((entry) => (
                    <TypeTile
                        key={entry.key}
                        name={entry.name}
                        icon={entry.icon}
                        selected={false}
                        disabledReason={entry.disabledReason}
                    />
                ))}
            </div>
            <div className="mt-2">
                <div className="text-sm font-semibold">{meta.name}</div>
                <div className="text-secondary text-xs">{meta.description}</div>
            </div>
            {viewOptions && onViewChange && (
                <div className="mt-3">
                    <div className="text-accent text-[0.625rem] font-semibold tracking-wide uppercase">View as</div>
                    <LemonSegmentedButton
                        size="xsmall"
                        fullWidth
                        className="mt-1"
                        value={viewValue ?? undefined}
                        onChange={(value) => onViewChange(value)}
                        options={viewOptions.map((option) => ({ value: option.value, label: option.label }))}
                    />
                </div>
            )}
        </div>
    )
}
