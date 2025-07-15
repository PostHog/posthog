import {
    type ExperimentVariantResult,
    formatChanceToWin,
    formatPValue,
    getIntervalLabel,
    getVariantInterval,
    isBayesianResult,
    valueToXCoordinate,
} from '../shared/utils'
import { BAR_HEIGHT, BAR_SPACING, SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'

export function VariantTooltip({
    variantResult,
    index,
    chartRadius,
    chartSvgRef,
    isVisible,
    onMouseEnter,
    onMouseLeave,
}: {
    variantResult: ExperimentVariantResult
    index: number
    chartRadius: number
    chartSvgRef: React.RefObject<SVGSVGElement>
    isVisible: boolean
    onMouseEnter?: () => void
    onMouseLeave?: () => void
}): JSX.Element | null {
    if (!isVisible || !chartSvgRef.current) {
        return null
    }

    // Calculate SVG coordinates (same as VariantBar)
    const interval = getVariantInterval(variantResult)
    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]

    const y = BAR_SPACING + (BAR_HEIGHT + BAR_SPACING) * index
    const x1 = valueToXCoordinate(lower, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    const x2 = valueToXCoordinate(upper, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)

    // Calculate middle of the bar
    const barCenterX = (x1 + x2) / 2
    const barTopY = y

    // Convert SVG coordinates to screen coordinates
    const svgRect = chartSvgRef.current.getBoundingClientRect()
    const svgViewBox = chartSvgRef.current.viewBox.baseVal

    const screenX = svgRect.left + (barCenterX / svgViewBox.width) * svgRect.width
    const screenY = svgRect.top + (barTopY / svgViewBox.height) * svgRect.height

    const intervalPercent = interval ? `[${(lower * 100).toFixed(2)}%, ${(upper * 100).toFixed(2)}%]` : 'N/A'
    const intervalLabel = getIntervalLabel(variantResult)

    return (
        <div
            className="fixed -translate-x-1/2 -translate-y-full bg-[var(--bg-surface-primary)] border border-[var(--border-primary)] px-3 py-2 rounded-md text-[13px] shadow-md z-[100] min-w-[300px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: screenX,
                top: screenY - 10,
                pointerEvents: 'auto',
            }}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
        >
            <div className="flex flex-col gap-1">
                <div className="font-semibold">{variantResult.key}</div>

                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">Samples:</span>
                    <span className="font-semibold">{variantResult.number_of_samples}</span>
                </div>

                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">Sum:</span>
                    <span className="font-semibold">{variantResult.sum}</span>
                </div>

                {isBayesianResult(variantResult) ? (
                    <div className="flex justify-between items-center">
                        <span className="text-secondary font-semibold">Chance to win:</span>
                        <span className="font-semibold">{formatChanceToWin(variantResult.chance_to_win)}</span>
                    </div>
                ) : (
                    <div className="flex justify-between items-center">
                        <span className="text-secondary font-semibold">P-value:</span>
                        <span className="font-semibold">{formatPValue(variantResult.p_value)}</span>
                    </div>
                )}

                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">Significant:</span>
                    <span className={`font-semibold ${variantResult.significant ? 'text-success' : 'text-muted'}`}>
                        {variantResult.significant ? 'Yes' : 'No'}
                    </span>
                </div>

                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">Delta:</span>
                    <span className="font-semibold">
                        {variantResult.key === 'control' ? (
                            <em className="text-secondary">Baseline</em>
                        ) : (
                            (() => {
                                const deltaPercent = interval ? ((lower + upper) / 2) * 100 : 0
                                const isPositive = deltaPercent > 0
                                return (
                                    <span className={isPositive ? 'text-success' : 'text-danger'}>
                                        {`${isPositive ? '+' : ''}${deltaPercent.toFixed(2)}%`}
                                    </span>
                                )
                            })()
                        )}
                    </span>
                </div>

                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">{intervalLabel}:</span>
                    <span className="font-semibold">{intervalPercent}</span>
                </div>
            </div>
        </div>
    )
}
