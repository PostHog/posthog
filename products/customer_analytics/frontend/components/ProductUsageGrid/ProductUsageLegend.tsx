import { LemonSegmentedButton } from '@posthog/lemon-ui'

import 'lib/components/DotMatrix/DotMatrix.scss'
import { DotMatrixLegend } from 'lib/components/DotMatrix/DotMatrixLegend'

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
}: {
    series: BookActivityMatrixProduct[]
    groupings: BookActivityMatrixGrouping[]
    grouping: string
    onGroupingChange: (key: string) => void
    selectedSeries: string[]
    onSelectedSeriesChange: (keys: string[]) => void
    mode?: 'dots' | 'count'
}): JSX.Element {
    const presentation = getProductUsageGrouping(series, groupings, grouping)
    return (
        <div className="flex flex-col gap-2" data-attr="product-usage-legend">
            <LemonSegmentedButton
                value={grouping}
                onChange={onGroupingChange}
                options={groupings.map(({ key, label }) => ({ value: key, label }))}
                size="small"
                data-attr="product-usage-grouping"
            />
            <DotMatrixLegend
                {...presentation}
                mode={mode}
                sizeThresholds={[1, 5, 10]}
                countScale={getProductUsageCountScale(selectedSeries.length > 0)}
                selectedSeries={selectedSeries}
                onSelectedSeriesChange={onSelectedSeriesChange}
                labels={{
                    itemLabel: 'product',
                    valueLabel: 'Users',
                    countLabel: getProductUsageCountLabel(series, selectedSeries),
                    selectionLabel: (count) => `Showing ${count} ${count === 1 ? 'product' : 'products'}`,
                }}
            />
        </div>
    )
}
