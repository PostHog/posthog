import { type ColumnDef, type SortingState } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconX } from '@posthog/icons'
import {
    Button,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Text,
    cn,
} from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AttributionMode, MarketingAnalyticsAttributionRow } from '~/queries/schema/schema-general'

import { ATTRIBUTION_ROW_LIMIT } from '../../logic/marketingAttributionLogic'
import { QuillColumnHeaderTooltip } from '../common/QuillColumnHeaderTooltip'
import { QuillTableLoadingRows } from '../common/QuillTableLoadingRows'
import { sortQuillTableRows } from '../sortQuillTableRows'
import { AttributionChart } from './AttributionChart'
import type { AttributionColumnGroup, AttributionNumericColumn } from './AttributionTable'

// A localStorage key: renaming it shows the notice again to people who dismissed it.
export const MODELS_IDENTICAL_DISMISS_KEY = 'marketing-attribution-models-identical'

const BREAKDOWN_COLUMN_ID = 'breakdown_value'

function numericColumnDef(column: AttributionNumericColumn): ColumnDef<MarketingAnalyticsAttributionRow, unknown> {
    const { fillPercent } = column
    return {
        id: column.key,
        accessorFn: (row: MarketingAnalyticsAttributionRow) => column.value(row),
        header: () => <QuillColumnHeaderTooltip title={column.title} tooltip={column.tooltip} />,
        sortDescFirst: false,
        meta: { align: 'right' },
        cell: ({ row }) => {
            const raw = column.value(row.original)
            if (raw === null) {
                return <span className="text-muted-foreground">-</span>
            }
            if (!fillPercent) {
                return <span className="tabular-nums">{column.format(raw)}</span>
            }
            return (
                <span className="relative block tabular-nums">
                    <span
                        aria-hidden
                        className="absolute inset-y-0 left-0 rounded-xs bg-info"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${fillPercent(row.original)}%` }}
                    />
                    <span className="relative">{column.format(raw)}</span>
                </span>
            )
        },
    }
}

export function QuillAttributionTable({
    metric,
    rows,
    models,
    columnGroups,
    dimensionLabel,
    loading,
    allModelsAgree,
    unattributed,
    totalConversions,
    windowDays,
}: {
    metric: 'conversions' | 'revenue'
    rows: MarketingAnalyticsAttributionRow[]
    models: AttributionMode[]
    columnGroups: AttributionColumnGroup[]
    dimensionLabel: string
    loading: boolean
    allModelsAgree: boolean
    unattributed: number
    totalConversions: number
    windowDays: number
}): JSX.Element {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: MODELS_IDENTICAL_DISMISS_KEY }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey: MODELS_IDENTICAL_DISMISS_KEY }))
    const [sorting, setSorting] = useState<SortingState>([{ id: 'influenced_conversions', desc: true }])

    const numericColumns = columnGroups.flatMap((group) => group.columns)
    const sortedRows = sortQuillTableRows(rows, sorting, {
        [BREAKDOWN_COLUMN_ID]: (a, b) => a.breakdownValue.localeCompare(b.breakdownValue),
        ...Object.fromEntries(numericColumns.map((column) => [column.key, column.sorter])),
    })

    const columns: ColumnDef<MarketingAnalyticsAttributionRow, unknown>[] = [
        {
            id: BREAKDOWN_COLUMN_ID,
            accessorFn: (row: MarketingAnalyticsAttributionRow) => row.breakdownValue,
            header: dimensionLabel,
            sortDescFirst: false,
            meta: { sticky: 'left' },
            cell: ({ row }) => (
                <span className="font-medium">
                    {row.original.breakdownValue || <span className="text-muted-foreground">(none)</span>}
                </span>
            ),
        },
        ...columnGroups
            .filter((group) => group.columns.length > 0)
            .map(
                (group): ColumnDef<MarketingAnalyticsAttributionRow, unknown> => ({
                    id: group.key,
                    header: () => <QuillColumnHeaderTooltip title={group.title} tooltip={group.tooltip} />,
                    columns: group.columns.map(numericColumnDef),
                })
            ),
    ]

    const showRowLimit = rows.length >= ATTRIBUTION_ROW_LIMIT

    return (
        <div className="flex flex-col gap-4">
            {!loading && allModelsAgree && !isDismissed && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Every model reports the same credit for this goal. That usually means people convert in
                            their first session, so each conversion has a single touchpoint and there is nothing to
                            split. Goals that happen later in the journey, like signing up or paying, show how the
                            models differ.
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button size="icon" aria-label="Dismiss" tooltip="Dismiss" onClick={dismiss}>
                            <IconX />
                        </Button>
                    </ItemActions>
                </Item>
            )}
            <AttributionChart
                metric={metric}
                rows={rows}
                models={models}
                dimensionLabel={dimensionLabel}
                loading={loading}
            />
            <div
                className={cn('flex flex-col gap-2 transition-opacity', loading && 'opacity-60')}
                aria-busy={loading || undefined}
            >
                <DataTable
                    columns={columns}
                    data={sortedRows}
                    getRowId={(row) => row.breakdownValue}
                    sorting={sorting}
                    onSortingChange={setSorting}
                    empty={
                        loading ? (
                            <QuillTableLoadingRows />
                        ) : (
                            <Empty>
                                <EmptyHeader>
                                    <EmptyDescription>
                                        {`No conversions were influenced by any ${dimensionLabel.toLowerCase()} in this date range.`}
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        )
                    }
                />
                {(unattributed > 0 || showRowLimit) && (
                    <div className="flex flex-col gap-1">
                        {unattributed > 0 && (
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {`${humanFriendlyNumber(unattributed)} of ${humanFriendlyNumber(totalConversions)} conversions had no touchpoints inside the ${windowDays}-day window, so they aren't credited to any row.`}
                            </Text>
                        )}
                        {showRowLimit && (
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {`Showing the top ${ATTRIBUTION_ROW_LIMIT} by influenced conversions. Sorting reorders these rows.`}
                            </Text>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
