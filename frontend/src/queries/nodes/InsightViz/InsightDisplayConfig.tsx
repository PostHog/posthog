import { PropsWithChildren, ReactNode } from 'react'
import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDisplayConfigLogic } from './insightDisplayConfigLogic'

import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { RetentionDatePicker } from 'scenes/insights/RetentionDatePicker'
import { RetentionReferencePicker } from 'scenes/insights/filters/RetentionReferencePicker'
import { PathStepPicker } from 'scenes/insights/views/Paths/PathStepPicker'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { ChartFilter } from 'lib/components/ChartFilter'
import { FunnelDisplayLayoutPicker } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'
import { ValueOnSeriesFilter } from 'scenes/insights/EditorFilters/ValueOnSeriesFilter'

interface InsightDisplayConfigProps {
    disableTable: boolean
}

export function InsightDisplayConfig({ disableTable }: InsightDisplayConfigProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        showDateRange,
        disableDateRange,
        showCompare,
        showValueOnSeries,
        showUnit,
        showChart,
        showInterval,
        showSmoothing,
        showRetention,
        showPaths,
        showFunnelDisplayLayout,
        showFunnelBins,
    } = useValues(insightDisplayConfigLogic(insightProps))

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2 gap-y-2">
                {showDateRange && !disableTable && (
                    <ConfigFilter>
                        <InsightDateFilter disabled={disableDateRange} />
                    </ConfigFilter>
                )}

                {showInterval && (
                    <ConfigFilter>
                        <IntervalFilter />
                    </ConfigFilter>
                )}

                {showSmoothing && (
                    <ConfigFilter>
                        <SmoothingFilter />
                    </ConfigFilter>
                )}

                {showRetention && (
                    <ConfigFilter>
                        <RetentionDatePicker />
                        <RetentionReferencePicker />
                    </ConfigFilter>
                )}

                {showPaths && (
                    <ConfigFilter>
                        <PathStepPicker />
                    </ConfigFilter>
                )}

                {showCompare && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}

                {showValueOnSeries && (
                    <ConfigFilter>
                        <ValueOnSeriesFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2 grow justify-end">
                {showUnit && (
                    <ConfigFilter>
                        <UnitPicker />
                    </ConfigFilter>
                )}

                {showChart && (
                    <ConfigFilter>
                        <ChartFilter />
                    </ConfigFilter>
                )}

                {showFunnelDisplayLayout && (
                    <ConfigFilter>
                        <FunnelDisplayLayoutPicker />
                    </ConfigFilter>
                )}

                {showFunnelBins && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )}
            </div>
        </div>
    )
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}
