import { ExperimentVariantResultFrequentist } from '~/queries/schema/schema-general'

import { VIEW_BOX_WIDTH } from './constants'
import { VariantBar } from './VariantBar'

export function Chart({
    chartSvgRef,
    chartHeight,
    variantResults,
    chartRadius,
    metricIndex,
    isSecondary,
}: {
    chartSvgRef: React.RefObject<SVGSVGElement>
    chartHeight: number
    variantResults: ExperimentVariantResultFrequentist[]
    chartRadius: number
    metricIndex: number
    isSecondary: boolean
}): JSX.Element {
    return (
        <div className="relative w-full">
            <div className="flex justify-center">
                <svg
                    ref={chartSvgRef}
                    viewBox={`0 0 ${VIEW_BOX_WIDTH} ${chartHeight}`}
                    preserveAspectRatio="xMidYMid meet"
                    className="ml-12 max-w-[1000px]"
                >
                    {/* Variant bars */}
                    {variantResults.map((variant: any, index: number) => (
                        <VariantBar
                            key={variant.key}
                            variant={variant}
                            index={index}
                            chartRadius={chartRadius}
                            metricIndex={metricIndex}
                            isSecondary={isSecondary}
                        />
                    ))}
                </svg>
            </div>
        </div>
    )
}
