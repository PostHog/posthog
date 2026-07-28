import './AttributionTable.scss'

import { BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonTable, LemonTableColumn, LemonTableColumnGroup, Tooltip } from '@posthog/lemon-ui'

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
    marketingAttributionLogic,
} from '../../logic/marketingAttributionLogic'

const MODEL_LABELS: Record<AttributionMode, string> = {
    [AttributionMode.FirstTouch]: 'First touch',
    [AttributionMode.LastTouch]: 'Last touch',
    [AttributionMode.Linear]: 'Linear',
    [AttributionMode.TimeDecay]: 'Time decay',
    [AttributionMode.PositionBased]: 'Position based',
}

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
    const logic = dataNodeLogic({ query, key, dataNodeCollectionId: key })
    const { response, responseLoading, responseError } = useValues(logic)
    const { breakdownBy } = useValues(marketingAttributionLogic)
    const { baseCurrency } = useValues(teamLogic)
    useAttachedLogic(logic, attachTo)

    const attributionResponse = response as MarketingAnalyticsAttributionQueryResponse | undefined
    const rows = attributionResponse?.results ?? []
    const models = attributionResponse?.models ?? []
    const hasValue = attributionResponse?.hasValue ?? false
    const windowDays = attributionResponse?.attributionWindowDays ?? 90
    const dimensionLabel = BREAKDOWN_LABELS[breakdownBy]

    // The bar tracks influenced conversions, the column the server ranked rows by. Scaled against the
    // largest row rather than the column total: model columns sum to the conversion count, so
    // share-of-total bars would be invisible on everything below the top row or two.
    const maxInfluenced = useMemo(() => Math.max(0, ...rows.map((row) => row.influencedConversions)), [rows])

    const columns: LemonTableColumnGroup<MarketingAnalyticsAttributionRow>[] = useMemo(() => {
        const numericColumn = (
            title: string,
            tooltip: string,
            value: (row: MarketingAnalyticsAttributionRow) => number | null,
            format: (value: number) => string,
            key: string
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
                        `People who arrived via this ${dimensionLabel.toLowerCase()} in the date range, whether or not they converted.`,
                        (row) => row.visitors,
                        (value) => humanFriendlyNumber(value),
                        'visitors'
                    ),
                    numericColumn(
                        'Conversions',
                        'Conversions with at least one touchpoint here. Counted once per conversion.',
                        (row) => row.influencedConversions,
                        (value) => humanFriendlyNumber(value),
                        'influenced_conversions'
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
                        // One decimal place: multi-touch credit is fractional, and rounding to whole
                        // numbers makes linear look identical to last touch at low volumes.
                        (value) => humanFriendlyNumber(value, 1),
                        `${model}_conversions`
                    ),
                    numericColumn(
                        'Conv. rate',
                        'Conversions credited by this model, divided by visitors. The denominator is the same for every model, so the rates are directly comparable.',
                        (row) => row.models[index]?.conversionRate ?? null,
                        (value) => percentage(value, 2),
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
    }, [dimensionLabel, hasValue, models, windowDays, baseCurrency])

    if (responseError) {
        return <InsightErrorState />
    }

    const unattributed = attributionResponse?.unattributedConversions ?? 0
    const totalConversions = attributionResponse?.totalConversions ?? 0

    return (
        <LemonTable
            className="AttributionTable"
            columns={columns}
            dataSource={rows}
            loading={responseLoading}
            rowKey="breakdownValue"
            firstColumnSticky
            defaultSorting={{ columnKey: 'influenced_conversions', order: -1 }}
            onRow={(row) => ({
                style: {
                    '--attribution-fill': `${
                        maxInfluenced > 0 ? Math.round((row.influencedConversions / maxInfluenced) * 100) : 0
                    }%`,
                } as React.CSSProperties,
            })}
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
    )
}
