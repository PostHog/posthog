import { type ExperimentVariantResult, isBayesianResult } from '../shared/utils'
import { NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { VIEW_BOX_WIDTH, SVG_EDGE_MARGIN, TICK_PANEL_HEIGHT, TICK_FONT_SIZE } from './constants'
import { ChartAxis } from '../shared/axis'

interface TableHeaderProps {
    results: NewExperimentQueryResponse[]
    chartRadius?: number
}

export function TableHeader({ results, chartRadius }: TableHeaderProps): JSX.Element {
    // Determine if we should show "P-value" or "Chance to Win" based on the first available result
    const firstVariantResult = results
        .map((result) => result?.variant_results?.[0])
        .find((variant): variant is ExperimentVariantResult => Boolean(variant))

    const isBayesian = firstVariantResult ? isBayesianResult(firstVariantResult) : false
    const significanceHeader = isBayesian ? 'Chance to Win' : 'P-value'

    return (
        <thead>
            <tr>
                <th className="w-1/5 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Metric
                </th>
                <th className="w-20 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Variant
                </th>
                <th className="w-24 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Value
                </th>
                <th className="w-20 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    {significanceHeader}
                </th>
                <th className="min-w-[400px] border-b-2 border-border bg-bg-table p-0 text-center text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    {chartRadius && chartRadius > 0 ? (
                        <div className="relative">
                            <svg
                                viewBox={`0 0 ${VIEW_BOX_WIDTH} ${TICK_PANEL_HEIGHT + 10}`}
                                preserveAspectRatio="xMidYMid meet"
                                className="w-full max-w-[1000px]"
                                style={{ minHeight: `${TICK_PANEL_HEIGHT + 10}px` }}
                            >
                                <ChartAxis
                                    chartRadius={chartRadius}
                                    height={TICK_PANEL_HEIGHT + 10}
                                    viewBoxWidth={VIEW_BOX_WIDTH}
                                    edgeMargin={SVG_EDGE_MARGIN}
                                    tickLabelsY={TICK_PANEL_HEIGHT / 2 + 2}
                                    tickLabelsProps={{
                                        fontSize: TICK_FONT_SIZE,
                                        fontWeight: '600',
                                    }}
                                />
                            </svg>
                        </div>
                    ) : (
                        <div className="p-3">Chart</div>
                    )}
                </th>
            </tr>
        </thead>
    )
}
