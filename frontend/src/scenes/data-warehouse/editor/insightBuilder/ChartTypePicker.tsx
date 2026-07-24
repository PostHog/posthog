import { useActions, useValues } from 'kea'

import { IconGraph, IconLifecycle, IconPieChart, IconTrends } from '@posthog/icons'

import { Icon123, IconAreaChart, IconHeatmap, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import {
    CHART_CAPABILITIES,
    validateWellsForDisplay,
} from '~/queries/nodes/DataVisualization/insightBuilder/chartCapabilities'
import { ChartDisplayType } from '~/types'

import { insightBuilderLogic } from './insightBuilderLogic'

const CHART_TYPE_ICONS: Partial<Record<ChartDisplayType, JSX.Element>> = {
    [ChartDisplayType.ActionsTable]: <IconTableChart />,
    [ChartDisplayType.BoldNumber]: <Icon123 />,
    [ChartDisplayType.ActionsLineGraph]: <IconTrends />,
    [ChartDisplayType.ActionsBar]: <IconGraph />,
    [ChartDisplayType.ActionsStackedBar]: <IconLifecycle />,
    [ChartDisplayType.ActionsAreaGraph]: <IconAreaChart />,
    [ChartDisplayType.ActionsPie]: <IconPieChart />,
    [ChartDisplayType.TwoDimensionalHeatmap]: <IconHeatmap />,
}

export function ChartTypePicker({ tabId }: { tabId: string }): JSX.Element {
    const { builderDisplay, wells } = useValues(insightBuilderLogic({ tabId }))
    const { setBuilderDisplay } = useActions(insightBuilderLogic({ tabId }))

    return (
        <div>
            <div className="text-xs font-semibold uppercase text-tertiary mb-1">Chart type</div>
            <div className="flex flex-wrap gap-1">
                {CHART_CAPABILITIES.map((capability) => {
                    const problems = validateWellsForDisplay(wells, capability.display)
                    const isActive = builderDisplay === capability.display
                    return (
                        <LemonButton
                            key={capability.display}
                            icon={CHART_TYPE_ICONS[capability.display]}
                            size="small"
                            type={isActive ? 'primary' : 'tertiary'}
                            active={isActive}
                            onClick={() => setBuilderDisplay(capability.display)}
                            tooltip={
                                <div>
                                    <div className="font-semibold">{capability.label}</div>
                                    <div>{capability.requirementHint}</div>
                                    {capability.tip ? <div className="text-muted">{capability.tip}</div> : null}
                                    {!isActive && problems.length > 0 ? (
                                        <div className="mt-1">{problems.join(' · ')}</div>
                                    ) : null}
                                </div>
                            }
                            data-attr={`sql-builder-chart-type-${capability.display}`}
                        />
                    )
                })}
            </div>
        </div>
    )
}
