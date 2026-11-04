import './ProductUsageLegend.scss'

import { LemonButton } from '@posthog/lemon-ui'

import 'lib/components/DotMatrix/DotMatrix.scss'
import { DotMatrixLegend } from 'lib/components/DotMatrix/DotMatrixLegend'
import { DotMatrixScaleKey } from 'lib/components/DotMatrix/DotMatrixScaleKey'
import { DotMatrixSymbol } from 'lib/components/DotMatrix/DotMatrixSymbol'

import type { BookActivityMatrixGrouping, BookActivityMatrixProduct } from '~/queries/schema/schema-general'

import {
    getProductUsageCountLabel,
    getProductUsageCountScale,
    getProductUsageGrouping,
} from './productUsagePresentation'

export function ProductUsageLegend({
    series,
    groupings,
    grouping,
    onGroupingChange,
    selectedSeries,
    onSelectedSeriesChange,
    mode = 'dots',
    hoveredSeries,
    onHoveredSeriesChange,
    includeFirstUse = false,
}: {
    series: BookActivityMatrixProduct[]
    groupings: BookActivityMatrixGrouping[]
    grouping: string
    onGroupingChange: (key: string) => void
    selectedSeries: string[]
    onSelectedSeriesChange: (keys: string[]) => void
    mode?: 'dots' | 'count' | 'users'
    hoveredSeries?: string | null
    onHoveredSeriesChange?: (key: string | null) => void
    includeFirstUse?: boolean
}): JSX.Element {
    const presentation = getProductUsageGrouping(series, groupings, grouping)
    return (
        <div className="ProductUsageLegend" data-attr="product-usage-legend">
            <div
                className="ProductUsageLegend__grouping"
                role="group"
                aria-label="Product grouping"
                data-attr="product-usage-grouping"
            >
                {groupings.map(({ key, label }) => (
                    <LemonButton
                        key={key}
                        size="small"
                        type={key === grouping ? 'secondary' : 'tertiary'}
                        aria-pressed={key === grouping}
                        onClick={() => onGroupingChange(key)}
                    >
                        {label}
                    </LemonButton>
                ))}
            </div>
            <DotMatrixLegend
                {...presentation}
                mode={mode === 'users' ? 'count' : mode}
                hoveredSeries={hoveredSeries}
                onHoveredSeriesChange={onHoveredSeriesChange}
                sizeThresholds={[1, 5, 10]}
                countScale={getProductUsageCountScale(selectedSeries.length > 0)}
                selectedSeries={selectedSeries}
                onSelectedSeriesChange={onSelectedSeriesChange}
                labels={{
                    footer:
                        mode === 'users' ? (
                            <span>{`Names = most active first · +N more = show all${includeFirstUse ? ' · New = first use ever' : ''}`}</span>
                        ) : (
                            <div className="flex flex-wrap items-center gap-3">
                                <DotMatrixScaleKey
                                    mode={mode}
                                    sizeThresholds={[1, 5, 10]}
                                    countScale={getProductUsageCountScale(selectedSeries.length > 0)}
                                    labels={{
                                        valueLabel: 'Users',
                                        countLabel: getProductUsageCountLabel(series, selectedSeries),
                                    }}
                                />
                                {mode === 'dots' && includeFirstUse && (
                                    <span className="inline-flex items-center gap-1">
                                        <svg width="17" height="17" viewBox="0 0 17 17" aria-hidden="true">
                                            <DotMatrixSymbol value={1} thresholds={[1]} color="currentColor" firstUse />
                                        </svg>
                                        <span>First use ever</span>
                                    </span>
                                )}
                            </div>
                        ),
                    itemLabel: 'product',
                    valueLabel: 'Users',
                    countLabel: getProductUsageCountLabel(series, selectedSeries),
                    selectionLabel: (count) => `Showing ${count} ${count === 1 ? 'product' : 'products'}`,
                }}
            />
        </div>
    )
}
