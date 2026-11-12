import './ProductUsageLegend.scss'

import { LemonButton } from '@posthog/lemon-ui'

import { DotMatrixLegend } from 'lib/components/DotMatrix/DotMatrixLegend'
import 'lib/components/DotMatrix/DotMatrix.scss'
import { DOT_MATRIX_SIZE_THRESHOLDS } from 'lib/components/DotMatrix/dotMatrixPresentation'
import { DotMatrixScaleKey } from 'lib/components/DotMatrix/DotMatrixScaleKey'

import type { BookActivityMatrixGrouping, BookActivityMatrixProduct } from '~/queries/schema/schema-general'

import { ProductUsageFirstUseStar } from '../ProductActivity/ProductUsageFirstUseStar'
import {
    getProductUsageCountLabel,
    getProductUsageCountScale,
    getProductUsageGrouping,
} from '../ProductActivity/productUsagePresentation'

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
                sizeThresholds={DOT_MATRIX_SIZE_THRESHOLDS}
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
                                    sizeThresholds={DOT_MATRIX_SIZE_THRESHOLDS}
                                    countScale={getProductUsageCountScale(selectedSeries.length > 0)}
                                    labels={{
                                        valueLabel: 'Users',
                                        countLabel: getProductUsageCountLabel(series, selectedSeries),
                                    }}
                                />
                                {mode === 'dots' && includeFirstUse && (
                                    <span className="inline-flex items-center gap-1">
                                        <ProductUsageFirstUseStar />
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
