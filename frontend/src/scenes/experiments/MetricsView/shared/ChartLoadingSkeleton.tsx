import clsx from 'clsx'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'

import { FIXED_HEIGHT_STYLE } from '~/scenes/experiments/MetricsView/shared/rowHeights'

export function SkeletonResultCells({
    variantKey,
    className,
    detailsCell,
}: {
    variantKey: string
    className: string
    // Rendered between P-value and Chart, with rowSpan, on the baseline row only; matches the real layout
    detailsCell?: JSX.Element
}): JSX.Element {
    return (
        <>
            {/* Variant tag is real; we know the variants before any result lands */}
            <td
                className={clsx('w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden', className)}
                style={FIXED_HEIGHT_STYLE}
            >
                <VariantTag variantKey={variantKey} />
            </td>

            {/* Value */}
            <td
                className={clsx('w-24 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden', className)}
                style={FIXED_HEIGHT_STYLE}
            >
                <LemonSkeleton className="h-4 w-12" />
            </td>

            {/* Delta */}
            <td
                className={clsx('w-20 pt-1 pl-3 pr-3 pb-1 text-left whitespace-nowrap overflow-hidden', className)}
                style={FIXED_HEIGHT_STYLE}
            >
                <LemonSkeleton className="h-4 w-10" />
            </td>

            {/* P-value / Win probability */}
            <td
                className={clsx('w-20 pt-1 pl-3 pr-3 pb-1 text-center whitespace-nowrap overflow-hidden', className)}
                style={FIXED_HEIGHT_STYLE}
            >
                <LemonSkeleton className="h-4 w-10 mx-auto" />
            </td>

            {detailsCell}

            {/* Chart: mirrors ChartCell's wrapper so the bar lands where the real chart will */}
            <td
                className={clsx('p-0 align-middle text-center relative overflow-hidden', className)}
                style={FIXED_HEIGHT_STYLE}
            >
                <div className="px-3">
                    <LemonSkeleton className="h-3 w-full" />
                </div>
            </td>
        </>
    )
}
