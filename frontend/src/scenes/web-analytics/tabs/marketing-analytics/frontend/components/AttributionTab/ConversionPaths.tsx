import './ConversionPaths.scss'

import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonSegmentedButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { formatCurrency } from 'lib/utils/currency'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    MarketingAnalyticsAttributionPathRow,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionPathsQueryResponse,
} from '~/queries/schema/schema-general'

import {
    MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID,
    PATHS_ROW_LIMIT,
    PathTouchpointFilter,
    marketingAttributionLogic,
} from '../../logic/marketingAttributionLogic'
import { BREAKDOWN_LABELS } from '../../logic/marketingBreakdown'
import { ConversionPathChips } from './ConversionPathChips'

// The segmented control offers exact lengths up to this, then an open-ended "N+" bucket.
const MAX_EXACT_TOUCHPOINTS = 3

// LemonSegmentedButton values must be React.Keys, so "any" stands in for the filter's null.
const TOUCHPOINT_OPTIONS: {
    value: number | 'any' | 'four_plus'
    label: string
    tooltip?: string
}[] = [
    { value: 'any', label: 'Any' },
    ...Array.from({ length: MAX_EXACT_TOUCHPOINTS }, (_, i) => ({
        value: i + 1,
        label: `${i + 1}`,
        tooltip: `Only journeys with exactly ${i + 1} touchpoint${i ? 's' : ''}`,
    })),
    {
        value: 'four_plus' as const,
        label: '4+',
        tooltip: 'Only journeys with four or more touchpoints',
    },
]

let uniqueNode = 0

export function ConversionPaths({
    query,
    attachTo,
}: {
    query: MarketingAnalyticsAttributionPathsQuery
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element {
    const [key] = useState(() => `MarketingAttributionPaths.${uniqueNode++}`)
    // Registered under the tab's shared collection so the filter bar's ReloadAll reaches this query.
    const logic = dataNodeLogic({
        query,
        key,
        dataNodeCollectionId: MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID,
    })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const { breakdownBy, pathTouchpointFilter } = useValues(marketingAttributionLogic)
    const { setPathTouchpointFilter } = useActions(marketingAttributionLogic)
    const { baseCurrency } = useValues(teamLogic)
    useAttachedLogic(logic, attachTo)

    const pathsResponse = response as MarketingAnalyticsAttributionPathsQueryResponse | undefined
    const rows = pathsResponse?.results ?? []
    const hasValue = pathsResponse?.hasValue ?? false
    const attributedConversions = pathsResponse?.attributedConversions ?? 0
    const dimensionLabel = BREAKDOWN_LABELS[breakdownBy]

    // One color per breakdown value, ranked by how many conversions the value participates in, so the
    // most prominent value on screen takes the first series color and every row paints "google" alike.
    const colorFor = useMemo(() => {
        const totals = new Map<string, number>()
        for (const row of rows) {
            for (const step of row.path) {
                totals.set(step, (totals.get(step) ?? 0) + row.conversions)
            }
        }
        const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([value]) => value)
        const colors = new Map(ranked.map((value, rank) => [value, getSeriesColor(rank)]))
        return (value: string): string => colors.get(value) ?? getSeriesColor(0)
    }, [rows])

    const maxConversions = Math.max(0, ...rows.map((row) => row.conversions))

    const columns: LemonTableColumns<MarketingAnalyticsAttributionPathRow> = [
        {
            title: 'Path',
            key: 'path',
            render: (_, row) => (
                <ConversionPathChips path={row.path} truncated={row.pathTruncated} colorFor={colorFor} />
            ),
        },
        {
            title: 'Conversions',
            key: 'conversions',
            align: 'right',
            width: 140,
            render: (_, row) => humanFriendlyNumber(row.conversions),
            sorter: (a, b) => a.conversions - b.conversions,
            className: 'ConversionPaths__magnitude-cell',
            style: (_, row) =>
                ({
                    '--conversion-paths-fill': `${
                        maxConversions > 0 ? Math.round((row.conversions / maxConversions) * 100) : 0
                    }%`,
                }) as React.CSSProperties,
        },
        {
            title: 'Share',
            tooltip: `This path's share of every conversion that had at least one touchpoint, whatever its length — so shares stay comparable when the touchpoint filter changes.`,
            key: 'share',
            align: 'right',
            width: 100,
            render: (_, row) =>
                attributedConversions > 0 ? (
                    percentage(row.conversions / attributedConversions, 1)
                ) : (
                    <span className="text-secondary">-</span>
                ),
            sorter: (a, b) => a.conversions - b.conversions,
        },
        ...(hasValue
            ? [
                  {
                      title: 'Value',
                      key: 'value',
                      align: 'right' as const,
                      width: 120,
                      render: (_: unknown, row: MarketingAnalyticsAttributionPathRow) =>
                          row.conversionValue === null ? (
                              <span className="text-secondary">-</span>
                          ) : (
                              formatCurrency(row.conversionValue, baseCurrency)
                          ),
                      sorter: (a: MarketingAnalyticsAttributionPathRow, b: MarketingAnalyticsAttributionPathRow) =>
                          (a.conversionValue ?? -1) - (b.conversionValue ?? -1),
                  },
              ]
            : []),
    ]

    const emptyState =
        pathTouchpointFilter === null
            ? `No conversions had any ${dimensionLabel.toLowerCase()} touchpoints in this date range.`
            : pathTouchpointFilter === 'four_plus'
              ? 'No conversion journeys had four or more touchpoints in this date range.'
              : `No conversion journeys had exactly ${pathTouchpointFilter} touchpoint${
                    pathTouchpointFilter === 1 ? '' : 's'
                } in this date range.`

    return (
        <div className="ConversionPaths flex flex-col gap-2 rounded border bg-surface-primary p-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                    <h3 className="mb-0 text-base font-semibold">Conversion paths</h3>
                    <p className="mb-0 text-secondary">
                        The most common journeys through your {dimensionLabel.toLowerCase()} touchpoints, oldest touch
                        first, ranked by the conversions they ended in.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <span className="text-secondary">Touchpoints</span>
                    <LemonSegmentedButton
                        size="small"
                        value={pathTouchpointFilter ?? 'any'}
                        onChange={(value) =>
                            setPathTouchpointFilter((value === 'any' ? null : value) as PathTouchpointFilter)
                        }
                        options={TOUCHPOINT_OPTIONS.map((option) => ({
                            ...option,
                            'data-attr': `marketing-attribution-path-touchpoints-${option.value}`,
                        }))}
                    />
                </div>
            </div>
            {responseError ? (
                <InsightErrorState
                    query={query}
                    excludeDetail
                    title={responseError}
                    onRetry={() => loadData('force_blocking')}
                />
            ) : (
                <LemonTable
                    columns={columns}
                    dataSource={rows}
                    loading={responseLoading}
                    rowKey={(row) => row.path.join('→')}
                    emptyState={emptyState}
                    footer={
                        pathsResponse?.hasMore ? (
                            <div className="px-2 py-2 text-secondary">
                                Showing the top {PATHS_ROW_LIMIT} paths by conversions.
                            </div>
                        ) : undefined
                    }
                />
            )}
        </div>
    )
}
