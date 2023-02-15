import { PropsWithChildren, ReactNode } from 'react'
import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDisplayConfigLogic } from './insightDisplayConfigLogic'

import { InsightDateFilter } from 'scenes/insights/filters/InsightDateFilter'
import { IntervalFilter } from 'lib/components/IntervalFilter'
import { SmoothingFilter } from 'lib/components/SmoothingFilter/SmoothingFilter'
import { RetentionDatePickerDataExploration } from 'scenes/insights/RetentionDatePicker'
import { RetentionReferencePickerDataExploration } from 'scenes/insights/filters/RetentionReferencePicker'
import { PathStepPickerDataExploration } from 'scenes/insights/views/Paths/PathStepPicker'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { UnitPicker } from 'lib/components/UnitPicker/UnitPicker'
import { ChartFilter } from 'lib/components/ChartFilter'
import { FunnelDisplayLayoutPickerDataExploration } from 'scenes/insights/views/Funnels/FunnelDisplayLayoutPicker'
import { ShowValuesFilter } from 'lib/components/ShowValueFilter'

// import { FunnelBinsPicker } from 'scenes/insights/views/Funnels/FunnelBinsPicker'

interface InsightDisplayConfigProps {
    disableTable: boolean
}

export function InsightDisplayConfig({ disableTable }: InsightDisplayConfigProps): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const { setFilters } = useActions(insightLogic)
    const {
        showDateRange,
        disableDateRange,
        showCompare,
        showUnit,
        showChart,
        showInterval,
        showSmoothing,
        showRetention,
        showPaths,
        showFunnelDisplayLayout,
        showValuesOnSeries,
        // showFunnelBins,
    } = useValues(insightDisplayConfigLogic(insightProps))

    return (
        <div className="flex justify-between items-center flex-wrap" data-attr="insight-filters">
            <div className="flex items-center space-x-2 flex-wrap my-2">
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
                        <RetentionDatePickerDataExploration />
                        <RetentionReferencePickerDataExploration />
                    </ConfigFilter>
                )}

                {showPaths && (
                    <ConfigFilter>
                        <PathStepPickerDataExploration />
                    </ConfigFilter>
                )}

                {showCompare && (
                    <ConfigFilter>
                        <CompareFilter />
                    </ConfigFilter>
                )}

                {showValuesOnSeries && (
                    <ConfigFilter>
                        <ShowValuesFilter />
                    </ConfigFilter>
                )}
            </div>
            <div className="flex items-center space-x-4 flex-wrap my-2">
                {showUnit && (
                    <ConfigFilter>
                        <UnitPicker filters={filters} setFilters={setFilters} />
                    </ConfigFilter>
                )}

                {showChart && (
                    <ConfigFilter>
                        <ChartFilter filters={filters} />
                    </ConfigFilter>
                )}

                {showFunnelDisplayLayout && (
                    <ConfigFilter>
                        <FunnelDisplayLayoutPickerDataExploration />
                    </ConfigFilter>
                )}

                {/* {showFunnelBins && (
                    <ConfigFilter>
                        <FunnelBinsPicker />
                    </ConfigFilter>
                )} */}
            </div>
        </div>
    )
}

function ConfigFilter(props: PropsWithChildren<ReactNode>): JSX.Element {
    return <span className="space-x-2 flex items-center text-sm">{props.children}</span>
}
