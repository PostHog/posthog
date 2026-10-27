import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ChartDisplayType } from '~/types'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { getChartTypeOptions } from 'products/business_intelligence/frontend/biEditorOptions'

/** Chart picker that highlights the chart types that suit the fields on the shelves. */
export function BIChartTypes(): JSX.Element {
    const { chartFits, config, hoveredChartType } = useValues(biEditorLogic)
    const { setChartType, setHoveredChartType } = useActions(biEditorLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const options = getChartTypeOptions(featureFlags)
    const describedOption =
        options.find((option) => option.value === hoveredChartType) ??
        options.find((option) => option.value === config.chartType)
    const describedFit = describedOption ? chartFits[describedOption.value] : undefined

    return (
        <div className="flex flex-col">
            <div className="grid grid-cols-4 gap-1 p-2" role="group" aria-label="Chart type">
                {options.map((option) => {
                    const fits = chartFits[option.value]?.fits ?? true
                    const selected = config.chartType === option.value
                    return (
                        <LemonButton
                            key={option.value}
                            type={selected ? 'primary' : 'tertiary'}
                            active={selected}
                            icon={option.icon}
                            size="small"
                            center
                            className={!fits && !selected ? 'opacity-40' : undefined}
                            tooltip={option.label}
                            aria-label={option.label}
                            aria-pressed={selected}
                            onClick={() => setChartType(option.value)}
                            onMouseEnter={() => setHoveredChartType(option.value)}
                            onMouseLeave={() => setHoveredChartType(null)}
                            data-attr={`bi-editor-chart-type-${option.value}`}
                        />
                    )
                })}
            </div>
            {describedOption && describedFit ? (
                <div className="border-t px-2 py-2 text-xs">
                    <div className="font-semibold">{describedOption.label}</div>
                    <div className="text-secondary">
                        {describedOption.value === ChartDisplayType.Auto
                            ? `${describedFit.requirement}.`
                            : `${describedFit.fits ? 'Uses' : 'Needs'} ${describedFit.requirement}.`}
                    </div>
                </div>
            ) : null}
        </div>
    )
}
