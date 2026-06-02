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

let uniqueNode = 0

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

    const minWidthRems = 12

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

    return (
        <div
            className="grid gap-2"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${minWidthRems}rem, 1fr))` }}
        >
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
