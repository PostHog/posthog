import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { buildTheme } from 'lib/charts/utils/theme'
import { type ChartTheme, Metric } from 'lib/hog-charts'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { isNotNil, range } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { WEB_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { formatItem, OverviewItem } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import {
    ActionsNode,
    AnyEntityNode,
    EventsNode,
    NodeKind,
    TrendsQuery,
    TrendsQueryResponse,
    WebOverviewQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyMathType, TrendResult } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

// Changes larger than this are treated as "was zero in the previous period" and the pill is suppressed,
// matching OverviewItemCell's handling of the backend's sentinel value.
const CHANGE_SENTINEL = 999999

const SPARKLINE_HEIGHT = 50

interface SparklineSeriesDef {
    /** Matches the `key` the WebOverview backend emits for the metric. */
    key: string
    node: AnyEntityNode
}

/** Build the trends series whose daily values feed each overview tile's sparkline. Mirrors the
 *  series the web-analytics graphs tab uses, so the sparkline matches the larger chart. */
export function buildWebOverviewSparklineSeries(
    useScreen: boolean,
    conversionGoal: WebOverviewQuery['conversionGoal']
): SparklineSeriesDef[] {
    const event = useScreen ? '$screen' : '$pageview'

    const defs: SparklineSeriesDef[] = [
        {
            key: 'visitors',
            node: { kind: NodeKind.EventsNode, event, math: BaseMathType.UniqueUsers, name: 'Visitors' },
        },
        { key: 'views', node: { kind: NodeKind.EventsNode, event, math: BaseMathType.TotalCount, name: 'Views' } },
        {
            key: 'sessions',
            node: { kind: NodeKind.EventsNode, event, math: BaseMathType.UniqueSessions, name: 'Sessions' },
        },
        {
            key: 'session duration',
            node: {
                kind: NodeKind.EventsNode,
                event,
                math: PropertyMathType.Average,
                math_property: '$session_duration',
                math_property_type: 'session_properties',
                name: 'Session duration',
            },
        },
        {
            key: 'bounce rate',
            node: {
                kind: NodeKind.EventsNode,
                event,
                math: PropertyMathType.Average,
                math_property: '$is_bounce',
                math_property_type: 'session_properties',
                name: 'Bounce rate',
            },
        },
    ]

    if (conversionGoal) {
        const uniqueConversions: EventsNode | ActionsNode =
            'actionId' in conversionGoal
                ? {
                      kind: NodeKind.ActionsNode,
                      id: conversionGoal.actionId,
                      math: BaseMathType.UniqueUsers,
                      name: 'Unique conversions',
                  }
                : {
                      kind: NodeKind.EventsNode,
                      event: conversionGoal.customEventName,
                      math: BaseMathType.UniqueUsers,
                      name: 'Unique conversions',
                  }
        defs.push({ key: 'unique conversions', node: uniqueConversions })
        defs.push({
            key: 'total conversions',
            node: { ...uniqueConversions, math: BaseMathType.TotalCount, name: 'Total conversions' },
        })
    }

    return defs
}

/** Map trends results back to overview keys by series order. Relies on the sparkline query
 *  disabling compare, so results are one current-period series per def, in order. */
export function mapSparklineSeriesByKey(
    defs: SparklineSeriesDef[],
    results: TrendResult[] | undefined
): Record<string, number[]> {
    const byKey: Record<string, number[]> = {}
    if (!results) {
        return byKey
    }
    defs.forEach((def, index) => {
        const data = results[index]?.data
        if (Array.isArray(data)) {
            byKey[def.key] = data
        }
    })
    return byKey
}

function MetricTile({
    item,
    labelFromKey,
    sparkline,
    theme,
    baseCurrency,
}: {
    item: OverviewItem
    labelFromKey: (key: string) => string
    sparkline: number[] | undefined
    theme: ChartTheme
    baseCurrency: string
}): JSX.Element {
    const value = typeof item.value === 'number' ? item.value : undefined
    const previous = typeof item.previous === 'number' ? item.previous : undefined
    const formatValue = (n: number): string => formatItem(n, item.kind, { currency: baseCurrency })

    const hasMeaningfulChange =
        isNotNil(item.changeFromPreviousPct) && Math.abs(item.changeFromPreviousPct) < CHANGE_SENTINEL
    const color = item.isIncreaseBad ? theme.colors[4] : theme.colors[0]

    return (
        <div className="flex flex-col rounded border border-primary bg-surface-primary px-3.5 py-3 transition-colors">
            <Metric
                className="text-primary"
                title={labelFromKey(item.key)}
                value={value}
                data={sparkline && sparkline.length > 0 ? sparkline : undefined}
                theme={theme}
                color={color}
                goodDirection={item.isIncreaseBad ? 'down' : 'up'}
                formatValue={formatValue}
                change={hasMeaningfulChange ? { value: item.changeFromPreviousPct as number } : null}
                subtitle={isNotNil(previous) ? `vs. ${formatValue(previous)} prior` : undefined}
                sparklineHeight={SPARKLINE_HEIGHT}
                sparklineClassName="mt-3 -mx-3.5 -mb-3"
            />
        </div>
    )
}

const GRID_STYLE = { gridTemplateColumns: `repeat(auto-fit, minmax(12rem, 1fr))` }

function MetricTilesGrid({
    items,
    sparklineByKey,
    labelFromKey,
    theme,
    baseCurrency,
}: {
    items: OverviewItem[]
    sparklineByKey: Record<string, number[]>
    labelFromKey: (key: string) => string
    theme: ChartTheme
    baseCurrency: string
}): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="grid gap-2" style={GRID_STYLE}>
            {items.map((item) => (
                <MetricTile
                    key={item.key}
                    item={item}
                    labelFromKey={labelFromKey}
                    sparkline={sparklineByKey[item.key]}
                    theme={theme}
                    baseCurrency={baseCurrency}
                />
            ))}
        </div>
    )
}

let uniqueNode = 0

/** Fallback for teams without precompute: fetch the per-day series with a raw trends query. */
function TrendsSparklineFallback({
    query,
    items,
    labelFromKey,
    useScreen,
    theme,
    baseCurrency,
    attachTo,
    uniqueKey,
    dataNodeCollectionId,
}: {
    query: WebOverviewQuery
    items: OverviewItem[]
    labelFromKey: (key: string) => string
    useScreen: boolean
    theme: ChartTheme
    baseCurrency: string
    attachTo?: LogicWrapper | BuiltLogic
    uniqueKey?: string | number
    dataNodeCollectionId?: string
}): JSX.Element {
    const seriesDefs = useMemo(
        () => buildWebOverviewSparklineSeries(useScreen, query.conversionGoal),
        [useScreen, query.conversionGoal]
    )

    const sparklineQuery = useMemo<TrendsQuery>(
        () => ({
            kind: NodeKind.TrendsQuery,
            dateRange: query.dateRange,
            interval: query.interval ?? 'day',
            series: seriesDefs.map((def) => def.node),
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            // Current period only — compare would interleave previous-period series and break the order mapping.
            filterTestAccounts: query.filterTestAccounts,
            conversionGoal: query.conversionGoal,
            properties: query.properties,
            sampling: query.sampling,
            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
        }),
        [query, seriesDefs]
    )

    const [_key] = useState(() => `WebOverviewSparkline.${uniqueNode++}`)
    const key = uniqueKey ? `${uniqueKey}-sparkline` : _key
    const sparklineLogic = dataNodeLogic({
        query: sparklineQuery,
        key,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })
    const { response } = useValues(sparklineLogic)
    useAttachedLogic(sparklineLogic, attachTo)

    const sparklineByKey = useMemo(
        () =>
            mapSparklineSeriesByKey(
                seriesDefs,
                (response as TrendsQueryResponse | undefined)?.results as TrendResult[] | undefined
            ),
        [seriesDefs, response]
    )

    return (
        <MetricTilesGrid
            items={items}
            sparklineByKey={sparklineByKey}
            labelFromKey={labelFromKey}
            theme={theme}
            baseCurrency={baseCurrency}
        />
    )
}

interface WebOverviewMetricGridProps {
    query: WebOverviewQuery
    items: OverviewItem[]
    loading: boolean
    numSkeletons: number
    labelFromKey: (key: string) => string
    useScreen: boolean
    attachTo?: LogicWrapper | BuiltLogic
    uniqueKey?: string | number
    dataNodeCollectionId?: string
}

export function WebOverviewMetricGrid({
    query,
    items,
    loading,
    numSkeletons,
    labelFromKey,
    useScreen,
    attachTo,
    uniqueKey,
    dataNodeCollectionId,
}: WebOverviewMetricGridProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { baseCurrency } = useValues(teamLogic)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- theme reads CSS vars that flip with dark mode
    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])

    if (loading) {
        return (
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3 lg:grid-cols-5">
                {range(numSkeletons).map((i) => (
                    <div
                        key={i}
                        className="flex flex-col gap-2 rounded border border-primary bg-surface-primary px-3.5 py-3"
                    >
                        <LemonSkeleton className="h-3 w-16" />
                        <LemonSkeleton className="h-7 w-20" />
                        <LemonSkeleton className="h-[50px] w-full" />
                    </div>
                ))}
            </div>
        )
    }

    // Prefer the precomputed series the backend returns from the pre-aggregated tables; only fire a
    // raw trends query when none are present (non-precompute teams, conversion goals).
    const precomputed = items.filter((item) => Array.isArray(item.series) && item.series.length > 0)
    if (precomputed.length > 0) {
        const sparklineByKey: Record<string, number[]> = {}
        for (const item of precomputed) {
            sparklineByKey[item.key] = item.series as number[]
        }
        return (
            <MetricTilesGrid
                items={items}
                sparklineByKey={sparklineByKey}
                labelFromKey={labelFromKey}
                theme={theme}
                baseCurrency={baseCurrency}
            />
        )
    }

    return (
        <TrendsSparklineFallback
            query={query}
            items={items}
            labelFromKey={labelFromKey}
            useScreen={useScreen}
            theme={theme}
            baseCurrency={baseCurrency}
            attachTo={attachTo}
            uniqueKey={uniqueKey}
            dataNodeCollectionId={dataNodeCollectionId}
        />
    )
}
