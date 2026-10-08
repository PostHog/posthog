import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'

import { ChartDisplayType } from '~/types'

import { biEditorLogic } from '../biEditorLogic'
import { getChartTypeOptions } from '../biEditorOptions'

/** Chart picker that highlights the chart types that suit the fields on the shelves. */
export function BIShowMe({ docked }: { docked: boolean }): JSX.Element {
    const { chartFits, config, hoveredChartType } = useValues(biEditorLogic)
    const { setChartType, setShowMeOpen, setHoveredChartType } = useActions(biEditorLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const options = getChartTypeOptions(featureFlags)
    const describedOption =
        options.find((option) => option.value === hoveredChartType) ??
        options.find((option) => option.value === config.chartType)
    const describedFit = describedOption ? chartFits[describedOption.value] : undefined

    return (
        <div className={cn('flex flex-col', docked ? 'w-full' : 'w-44')}>
            <div className="flex min-h-7 items-center justify-between px-2 pt-2">
                <span className="text-sm font-semibold">Show me</span>
                {docked ? (
                    <LemonButton
                        icon={<IconX />}
                        size="xsmall"
                        type="tertiary"
                        tooltip="Hide chart picker"
                        aria-label="Hide chart picker"
                        onClick={() => setShowMeOpen(false)}
                    />
                ) : null}
            </div>
            <div className="grid grid-cols-3 gap-1 p-2 @6xl/bi-editor:grid-cols-6" role="group" aria-label="Chart type">
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
                            className={cn('justify-center', !fits && !selected && 'opacity-40')}
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
