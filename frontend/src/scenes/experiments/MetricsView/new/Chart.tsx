import { type ExperimentVariantResult } from '../shared/utils'
import { BAR_HEIGHT, BAR_SPACING, VIEW_BOX_WIDTH } from './constants'
import { GridLines } from './GridLines'
import { useTooltipHover } from './useTooltipHover'
import { VariantBar } from './VariantBar'
import { VariantTooltip } from './VariantTooltip'

export function Chart({
    chartSvgRef,
    variantResults,
    chartRadius,
    metricIndex,
    tickValues,
    isSecondary,
}: {
    chartSvgRef: React.RefObject<SVGSVGElement>
    variantResults: ExperimentVariantResult[]
    chartRadius: number
    metricIndex: number
    tickValues: number[]
    isSecondary: boolean
}): JSX.Element {
    const { showTooltip, hideTooltip, showTooltipFromTooltip, isTooltipVisible } = useTooltipHover()

    const chartHeight = Math.max(BAR_SPACING + (BAR_HEIGHT + BAR_SPACING) * variantResults.length, 70)

    return (
        <div className="relative w-full">
            <div className="flex justify-center">
                <svg
                    ref={chartSvgRef}
                    viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                    preserveAspectRatio="xMidYMid meet"
                    className="max-w-[1000px]"
                >
                    <g className="grid-lines-layer">
                        {/* Vertical grid lines */}
                        <GridLines tickValues={tickValues} chartRadius={chartRadius} chartHeight={chartHeight} />
                    </g>
                    <g className="variant-separators-layer">
                        {/* Horizontal separator lines between variants */}
                        {variantResults.map((_, index: number) => {
                            if (index === variantResults.length - 1) {
                                return null
                            } // Don't render line after last variant

                            const totalContentHeight = BAR_SPACING + variantResults.length * (BAR_HEIGHT + BAR_SPACING)
                            const verticalOffset = Math.max(0, (chartHeight - totalContentHeight) / 2)
                            const y =
                                verticalOffset +
                                BAR_SPACING +
                                (BAR_HEIGHT + BAR_SPACING) * (index + 1) -
                                BAR_SPACING / 2

                            return (
                                <line
                                    key={`separator-${index}`}
                                    x1={0}
                                    y1={y}
                                    x2={VIEW_BOX_WIDTH}
                                    y2={y}
                                    stroke="var(--border)"
                                    strokeWidth={1}
                                />
                            )
                        })}
                    </g>
                    <g className="variant-bars-layer">
                        {/* Variant bars */}
                        {variantResults.map((variantResult: ExperimentVariantResult, index: number) => (
                            <VariantBar
                                key={`variant-bar-${variantResult.key}`}
                                variantResult={variantResult}
                                index={index}
                                chartRadius={chartRadius}
                                metricIndex={metricIndex}
                                isSecondary={isSecondary}
                                chartHeight={chartHeight}
                                totalBars={variantResults.length}
                                onMouseEnter={() => showTooltip(variantResult.key)}
                                onMouseLeave={hideTooltip}
                            />
                        ))}
                    </g>
                </svg>
            </div>

            {variantResults.map((variantResult: ExperimentVariantResult, index: number) => (
                <VariantTooltip
                    key={`tooltip-${variantResult.key}`}
                    variantResult={variantResult}
                    index={index}
                    chartRadius={chartRadius}
                    chartSvgRef={chartSvgRef}
                    isVisible={isTooltipVisible(variantResult.key)}
                    onMouseEnter={() => showTooltipFromTooltip(variantResult.key)}
                    onMouseLeave={hideTooltip}
                />
            ))}
        </div>
    )
}
