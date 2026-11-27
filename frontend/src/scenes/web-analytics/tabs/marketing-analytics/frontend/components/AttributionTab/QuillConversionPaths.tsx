import { type ColumnDef, type SortingState } from '@tanstack/react-table'
import { useState } from 'react'

import {
    Card,
    CardContent,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    Text,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { formatCurrency } from 'lib/utils/currency'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { CurrencyCode, MarketingAnalyticsAttributionPathRow } from '~/queries/schema/schema-general'

import { PATHS_ROW_LIMIT } from '../../logic/marketingAttributionLogic'
import { QuillColumnHeaderTooltip } from '../common/QuillColumnHeaderTooltip'
import { QuillTableLoadingRows } from '../common/QuillTableLoadingRows'
import { sortQuillTableRows } from '../sortQuillTableRows'
import { ConversionPathChips } from './ConversionPathChips'
import type { ConversionPathSorter, TouchpointOption, TouchpointOptionValue } from './ConversionPaths'

export function QuillConversionPaths({
    rows,
    loading,
    errorState,
    dimensionLabel,
    touchpointOptions,
    touchpointValue,
    onTouchpointChange,
    colorFor,
    conversionsFillPercent,
    attributedConversions,
    hasValue,
    baseCurrency,
    sorters,
    shareTooltip,
    emptyState,
    hasMore,
}: {
    rows: MarketingAnalyticsAttributionPathRow[]
    loading: boolean
    errorState: JSX.Element | null
    dimensionLabel: string
    touchpointOptions: TouchpointOption[]
    touchpointValue: TouchpointOptionValue
    onTouchpointChange: (value: TouchpointOptionValue) => void
    colorFor: (value: string) => string
    conversionsFillPercent: (row: MarketingAnalyticsAttributionPathRow) => number
    attributedConversions: number
    hasValue: boolean
    baseCurrency: CurrencyCode
    sorters: Record<'conversions' | 'share' | 'value', ConversionPathSorter>
    shareTooltip: string
    emptyState: string
    hasMore: boolean
}): JSX.Element {
    const [sorting, setSorting] = useState<SortingState>([])
    const sortedRows = sortQuillTableRows(rows, sorting, sorters)

    const columns: ColumnDef<MarketingAnalyticsAttributionPathRow, unknown>[] = [
        {
            id: 'path',
            header: 'Path',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row }) => (
                // The chips mix their colors against Lemon surface tokens, which quill rebinds inside the table.
                <span data-not-quill className="contents">
                    <ConversionPathChips
                        path={row.original.path}
                        truncated={row.original.pathTruncated}
                        colorFor={colorFor}
                    />
                </span>
            ),
        },
        {
            id: 'conversions',
            accessorFn: (row: MarketingAnalyticsAttributionPathRow) => row.conversions,
            header: 'Conversions',
            sortDescFirst: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <span className="relative block tabular-nums">
                    <span
                        aria-hidden
                        className="absolute inset-y-0 left-0 rounded-xs bg-info"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ width: `${conversionsFillPercent(row.original)}%` }}
                    />
                    <span className="relative">{humanFriendlyNumber(row.original.conversions)}</span>
                </span>
            ),
        },
        {
            id: 'share',
            accessorFn: (row: MarketingAnalyticsAttributionPathRow) => row.conversions,
            header: () => <QuillColumnHeaderTooltip title="Share" tooltip={shareTooltip} />,
            sortDescFirst: false,
            meta: { align: 'right' },
            cell: ({ row }) =>
                attributedConversions > 0 ? (
                    <span className="tabular-nums">
                        {percentage(row.original.conversions / attributedConversions, 1)}
                    </span>
                ) : (
                    <span className="text-muted-foreground">-</span>
                ),
        },
        ...(hasValue
            ? [
                  {
                      id: 'value',
                      accessorFn: (row: MarketingAnalyticsAttributionPathRow) => row.conversionValue,
                      header: 'Value',
                      sortDescFirst: false,
                      meta: { align: 'right' },
                      cell: ({ row }) =>
                          row.original.conversionValue === null ? (
                              <span className="text-muted-foreground">-</span>
                          ) : (
                              <span className="tabular-nums">
                                  {formatCurrency(row.original.conversionValue, baseCurrency)}
                              </span>
                          ),
                  } satisfies ColumnDef<MarketingAnalyticsAttributionPathRow, unknown>,
              ]
            : []),
    ]

    return (
        <Card>
            <CardContent className="flex flex-col gap-2">
                <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="flex flex-col gap-1">
                        <Heading size="base" render={<h3 className="m-0" />}>
                            Conversion paths
                        </Heading>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {`The most common journeys through your ${dimensionLabel.toLowerCase()} touchpoints, oldest touch first, ranked by the conversions they ended in.`}
                        </Text>
                    </div>
                    <div className="flex items-center gap-2">
                        <Text size="xs" variant="muted" render={<span />}>
                            Touchpoints
                        </Text>
                        <ToggleGroup
                            variant="outline"
                            aria-label="Touchpoints"
                            value={[String(touchpointValue)]}
                            onValueChange={(next: string[]) => {
                                const picked = touchpointOptions.find((option) => String(option.value) === next[0])
                                if (picked) {
                                    onTouchpointChange(picked.value)
                                }
                            }}
                        >
                            {touchpointOptions.map((option) => (
                                <ToggleGroupItem
                                    key={option.value}
                                    value={String(option.value)}
                                    data-attr={`marketing-attribution-path-touchpoints-${option.value}`}
                                >
                                    {option.tooltip ? (
                                        <Tooltip>
                                            <TooltipTrigger render={<span />}>{option.label}</TooltipTrigger>
                                            <TooltipContent>{option.tooltip}</TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        option.label
                                    )}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                    </div>
                </div>
                {errorState ?? (
                    <div
                        className={cn('flex flex-col gap-2 transition-opacity', loading && 'opacity-60')}
                        aria-busy={loading || undefined}
                    >
                        <DataTable
                            columns={columns}
                            data={sortedRows}
                            getRowId={(row) => row.path.join('→')}
                            sorting={sorting}
                            onSortingChange={setSorting}
                            fullWidth
                            empty={
                                loading ? (
                                    <QuillTableLoadingRows />
                                ) : (
                                    <Empty>
                                        <EmptyHeader>
                                            <EmptyDescription>{emptyState}</EmptyDescription>
                                        </EmptyHeader>
                                    </Empty>
                                )
                            }
                        />
                        {hasMore && (
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                {`Showing the top ${PATHS_ROW_LIMIT} paths by conversions.`}
                            </Text>
                        )}
                    </div>
                )}
            </CardContent>
        </Card>
    )
}
