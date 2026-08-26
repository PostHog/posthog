import './AttributionTable.scss'

import clsx from 'clsx'
import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonTable, LemonTableColumn, LemonTableColumnGroup, Tooltip } from '@posthog/lemon-ui'

import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { formatCurrency } from 'lib/utils/currency'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { InsightErrorState } from 'scenes/insights/EmptyStates'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AttributionMode,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsAttributionQueryResponse,
    MarketingAnalyticsAttributionRow,
} from '~/queries/schema/schema-general'

import {
    ATTRIBUTION_ROW_LIMIT,
    BREAKDOWN_LABELS,
    MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID,
    MODEL_LABELS,
    marketingAttributionLogic,
} from '../../logic/marketingAttributionLogic'
import { AttributionChart } from './AttributionChart'

const modelTooltip = (model: AttributionMode, windowDays: number): string => {
    switch (model) {
        case AttributionMode.FirstTouch:
            return 'All credit goes to the earliest touchpoint in the attribution window.'
        case AttributionMode.LastTouch:
            return 'All credit goes to the most recent touchpoint before the conversion.'
        case AttributionMode.Linear:
            return 'Credit is split equally across every touchpoint.'
        case AttributionMode.TimeDecay:
            return `Touchpoints closer to the conversion get more credit. A touchpoint from ${Math.max(
                Math.round(windowDays / 4),
                1
            )} days before the conversion gets half the credit of one at conversion time.`
        case AttributionMode.PositionBased:
            return '40% of the credit goes to the first touchpoint, 40% to the last, and the remaining 20% is split across the rest.'
    }
}

let uniqueNode = 0

export function AttributionTable({
    query,
    attachTo,
}: {
    query: MarketingAnalyticsAttributionQuery
    attachTo?: LogicWrapper | BuiltLogic
}): JSX.Element {
    const [key] = useState(() => `MarketingAttribution.${uniqueNode++}`)
    // Registered under the tab's shared collection so the filter bar's ReloadAll reaches this query.
    const logic = dataNodeLogic({ query, key, dataNodeCollectionId: MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const { breakdownBy, effectiveLookbackDays } = useValues(marketingAttributionLogic)
    const { baseCurrency } = useValues(teamLogic)
    useAttachedLogic(logic, attachTo)

    const attributionResponse = response as MarketingAnalyticsAttributionQueryResponse | undefined
    const rows = attributionResponse?.results ?? []
    const models = attributionResponse?.models ?? []
    const hasValue = attributionResponse?.hasValue ?? false
    const windowDays = attributionResponse?.attributionWindowDays ?? effectiveLookbackDays
    const dimensionLabel = BREAKDOWN_LABELS[breakdownBy]

    // With repeat conversions counted, conversions-over-visitors is a ratio rather than a share, so it
    // must not be formatted as a percentage.
    const countsRepeatConversions = attributionResponse?.allowsMultipleConversionsPerVisitor ?? false
    const rateLabel = countsRepeatConversions ? 'Per visitor' : 'Conv. rate'
    const formatRate = (value: number): string =>
        countsRepeatConversions ? `${humanFriendlyNumber(value, 2)}x` : percentage(value, 2)

    // One scale across every conversions column is what makes bar lengths comparable between models.
    const maxInfluenced = Math.max(0, ...rows.map((row) => row.influencedConversions))

    const buildColumns = (): LemonTableColumnGroup<MarketingAnalyticsAttributionRow>[] => {
        const numericColumn = (
            title: string,
            tooltip: string,
            value: (row: MarketingAnalyticsAttributionRow) => number | null,
            format: (value: number) => string,
            key: string,
            options?: { withMagnitudeBar?: boolean; groupBoundary?: boolean }
        ): LemonTableColumn<MarketingAnalyticsAttributionRow, keyof MarketingAnalyticsAttributionRow | undefined> => ({
            title,
            tooltip,
            key,
            align: 'right',
            render: (_, row) => {
                const raw = value(row)
                return raw === null ? <span className="text-secondary">-</span> : format(raw)
            },
            sorter: (a, b) => (value(a) ?? -1) - (value(b) ?? -1),
            className: clsx(
                options?.withMagnitudeBar && 'AttributionTable__magnitude-cell',
                options?.groupBoundary && 'AttributionTable__group-boundary'
            ),
            ...(options?.withMagnitudeBar
                ? {
                      style: (_, row) =>
                          ({
                              '--attribution-fill': `${
                                  maxInfluenced > 0 ? Math.round(((value(row) ?? 0) / maxInfluenced) * 100) : 0
                              }%`,
                          }) as React.CSSProperties,
                  }
                : {}),
        })

        return [
            {
                children: [
                    {
                        title: dimensionLabel,
                        key: 'breakdown_value',
                        render: (_, row) => (
                            <span className="font-medium">
                                {row.breakdownValue || <span className="text-secondary">(none)</span>}
                            </span>
                        ),
                        sorter: (a, b) => a.breakdownValue.localeCompare(b.breakdownValue),
                    },
                ],
            },
            {
                title: (
                    <Tooltip
                        title={`Every visitor and conversion that touched this ${dimensionLabel.toLowerCase()} at least once inside the ${windowDays}-day attribution window. One conversion can be influenced by several of them, so these columns add up to more than your total conversions.`}
                    >
                        <span>Influenced</span>
                    </Tooltip>
                ),
                children: [
                    numericColumn(
                        'Visitors',
                        `People who arrived via this ${dimensionLabel.toLowerCase()}, whether or not they converted. Counts arrivals up to ${windowDays} days before the date range, since those visits can still earn credit for conversions in it.`,
                        (row) => row.visitors,
                        (value) => humanFriendlyNumber(value),
                        'visitors',
                        { groupBoundary: true }
                    ),
                    numericColumn(
                        'Conversions',
                        'Conversions with at least one touchpoint here. Counted once per conversion.',
                        (row) => row.influencedConversions,
                        (value) => humanFriendlyNumber(value),
                        'influenced_conversions',
                        { withMagnitudeBar: true }
                    ),
                    numericColumn(
                        rateLabel,
                        countsRepeatConversions
                            ? `Conversions this ${dimensionLabel.toLowerCase()} influenced, per visitor it brought. Above 1x when people convert more than once.`
                            : `The share of this ${dimensionLabel.toLowerCase()}'s visitors who went on to convert, whichever touchpoint gets the credit.`,
                        (row) => (row.visitors > 0 ? row.influencedConversions / row.visitors : null),
                        formatRate,
                        'influenced_rate'
                    ),
                    ...(hasValue
                        ? [
                              numericColumn(
                                  'Value',
                                  'Full value of every influenced conversion, also counted in full against the other rows that influenced it.',
                                  (row) => row.influencedValue,
                                  (value) => formatCurrency(value, baseCurrency),
                                  'influenced_value'
                              ),
                          ]
                        : []),
                ],
            },
            ...models.map((model, index) => ({
                title: (
                    <Tooltip title={modelTooltip(model, windowDays)}>
                        <span>{MODEL_LABELS[model]}</span>
                    </Tooltip>
                ),
                children: [
                    numericColumn(
                        'Conversions',
                        `Conversions credited to this ${dimensionLabel.toLowerCase()} by the ${MODEL_LABELS[
                            model
                        ].toLowerCase()} model. Fractional when credit is shared across touchpoints.`,
                        (row) => row.models[index]?.conversions ?? null,
                        // Multi-touch credit is fractional; whole numbers make linear look identical to
                        // last touch at low volumes.
                        (value) => humanFriendlyNumber(value, 1),
                        `${model}_conversions`,
                        { withMagnitudeBar: true, groupBoundary: true }
                    ),
                    numericColumn(
                        rateLabel,
                        'Conversions credited by this model, divided by visitors. The denominator is the same for every model, so the columns are directly comparable.',
                        (row) => row.models[index]?.conversionRate ?? null,
                        formatRate,
                        `${model}_rate`
                    ),
                    ...(hasValue
                        ? [
                              numericColumn(
                                  'Value',
                                  `Conversion value credited to this ${dimensionLabel.toLowerCase()} by the ${MODEL_LABELS[
                                      model
                                  ].toLowerCase()} model.`,
                                  (row) => row.models[index]?.conversionValue ?? null,
                                  (value) => formatCurrency(value, baseCurrency),
                                  `${model}_value`
                              ),
                          ]
                        : []),
                ],
            })),
        ]
    }

    const columns = buildColumns()

    if (responseError) {
        return (
            <InsightErrorState
                query={query}
                excludeDetail
                title={responseError}
                onRetry={() => loadData('force_blocking')}
            />
        )
    }

    const unattributed = attributionResponse?.unattributedConversions ?? 0
    const totalConversions = attributionResponse?.totalConversions ?? 0

    // Models only differ when a conversion has more than one touchpoint, so identical numbers across the
    // board almost always means the goal converts on the visitor's first session.
    const allModelsAgree =
        rows.length > 0 &&
        rows.every((row) => {
            const conversions = row.models.map((cell) => cell.conversions)
            return Math.max(...conversions) - Math.min(...conversions) < 0.05
        })

    return (
        <div className="flex flex-col gap-4">
            {!responseLoading && allModelsAgree && (
                <LemonBanner type="info" dismissKey="marketing-attribution-models-identical">
                    Every model reports the same credit for this goal. That usually means people convert in their first
                    session, so each conversion has a single touchpoint and there is nothing to split. Goals that happen
                    later in the journey, like signing up or paying, show how the models differ.
                </LemonBanner>
            )}
            <AttributionChart rows={rows} models={models} dimensionLabel={dimensionLabel} loading={responseLoading} />
            <LemonTable
                className="AttributionTable"
                columns={columns}
                dataSource={rows}
                loading={responseLoading}
                rowKey="breakdownValue"
                firstColumnSticky
                defaultSorting={{ columnKey: 'influenced_conversions', order: -1 }}
                emptyState={`No conversions were influenced by any ${dimensionLabel.toLowerCase()} in this date range.`}
                footer={
                    unattributed > 0 || rows.length >= ATTRIBUTION_ROW_LIMIT ? (
                        <div className="flex flex-col gap-1 px-2 py-2 text-secondary">
                            {unattributed > 0 && (
                                <span>
                                    {humanFriendlyNumber(unattributed)} of {humanFriendlyNumber(totalConversions)}{' '}
                                    conversions had no touchpoints inside the {windowDays}-day window, so they aren't
                                    credited to any row.
                                </span>
                            )}
                            {rows.length >= ATTRIBUTION_ROW_LIMIT && (
                                <span>
                                    Showing the top {ATTRIBUTION_ROW_LIMIT} by influenced conversions. Sorting reorders
                                    these rows.
                                </span>
                            )}
                        </div>
                    ) : undefined
                }
            />
        </div>
    )
}
