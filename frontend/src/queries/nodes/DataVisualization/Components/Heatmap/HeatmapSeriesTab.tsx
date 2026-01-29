import { useActions, useValues } from 'kea'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonColorPicker,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonTag,
} from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'

import { HeatmapGradientStop, HeatmapSettings } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import { HEATMAP_GRADIENT_PRESETS, resolveGradientStops, sortGradientStops } from './heatmapUtils'

const defaultGradientStops = resolveGradientStops(undefined)

const normalizeNumberInput = (value: string | number): number => {
    const valueAsString = `${value}`

    if (valueAsString.trim() === '') {
        return 0
    }

    const parsedValue = Number(valueAsString)
    if (Number.isNaN(parsedValue)) {
        return 0
    }

    return parsedValue
}

export const HeatmapSeriesTab = (): JSX.Element => {
    const { columns, numericalColumns, responseLoading, chartSettings } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)

    const heatmapSettings = chartSettings.heatmap ?? ({} as HeatmapSettings)
    const gradientStops = heatmapSettings.gradient ?? defaultGradientStops

    const updateHeatmapSettings = (partial: Partial<HeatmapSettings>): void => {
        updateChartSettings({
            heatmap: {
                ...heatmapSettings,
                ...partial,
            },
        })
    }

    const updateGradientStops = (stops: HeatmapGradientStop[]): void => {
        updateHeatmapSettings({ gradient: sortGradientStops(stops), gradientPreset: 'custom' })
    }

    const columnOptions = columns.map(({ name, type }) => ({
        value: name,
        label: (
            <div className="items-center flex-1">
                {name}
                <LemonTag className="ml-2" type="default">
                    {type.name}
                </LemonTag>
            </div>
        ),
    }))

    const numericalOptions = numericalColumns.map(({ name, type }) => ({
        value: name,
        label: (
            <div className="items-center flex-1">
                {name}
                <LemonTag className="ml-2" type="default">
                    {type.name}
                </LemonTag>
            </div>
        ),
    }))

    return (
        <div className="flex flex-col w-full p-3 gap-4">
            <div>
                <LemonLabel className="mb-1">X-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={heatmapSettings.xAxisColumn ?? 'None'}
                    options={columnOptions}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => updateHeatmapSettings({ xAxisColumn: value ?? undefined })}
                />
                <LemonLabel className="mt-2 mb-1">X-axis label</LemonLabel>
                <LemonInput
                    value={heatmapSettings.xAxisLabel ?? ''}
                    placeholder={heatmapSettings.xAxisColumn ?? 'X-axis label'}
                    onChange={(value) => updateHeatmapSettings({ xAxisLabel: value })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1">Y-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={heatmapSettings.yAxisColumn ?? 'None'}
                    options={columnOptions}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => updateHeatmapSettings({ yAxisColumn: value ?? undefined })}
                />
                <LemonLabel className="mt-2 mb-1">Y-axis label</LemonLabel>
                <LemonInput
                    value={heatmapSettings.yAxisLabel ?? ''}
                    placeholder={heatmapSettings.yAxisColumn ?? 'Y-axis label'}
                    onChange={(value) => updateHeatmapSettings({ yAxisLabel: value })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1">Value</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={heatmapSettings.valueColumn ?? 'None'}
                    options={numericalOptions}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => updateHeatmapSettings({ valueColumn: value ?? undefined })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1">Gradient preset</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={heatmapSettings.gradientPreset ?? 'custom'}
                    options={[
                        { value: 'custom', label: 'Custom' },
                        ...HEATMAP_GRADIENT_PRESETS.map((preset) => ({
                            value: preset.value,
                            label: preset.label,
                        })),
                    ]}
                    onChange={(value) => {
                        if (!value || value === 'custom') {
                            updateHeatmapSettings({ gradientPreset: 'custom' })
                            return
                        }

                        const preset = HEATMAP_GRADIENT_PRESETS.find((entry) => entry.value === value)
                        if (!preset) {
                            return
                        }

                        updateHeatmapSettings({
                            gradient: preset.stops.map((stop) => ({ ...stop })),
                            gradientPreset: preset.value,
                            gradientScaleMode: 'relative',
                        })
                    }}
                />
                <LemonCheckbox
                    className="mt-2"
                    label="Scale gradient to data range"
                    checked={heatmapSettings.gradientScaleMode === 'relative'}
                    onChange={(checked) =>
                        updateHeatmapSettings({ gradientScaleMode: checked ? 'relative' : 'absolute' })
                    }
                />
                <LemonLabel className="mt-4 mb-2">Gradient</LemonLabel>
                <div className="flex flex-col gap-2">
                    {gradientStops.map((stop, index) => (
                        <div key={`${stop.color}-${index}`} className="flex items-center gap-2">
                            <LemonColorPicker
                                selectedColor={stop.color}
                                onSelectColor={(color) => {
                                    const nextStops = [...gradientStops]
                                    nextStops[index] = { ...nextStops[index], color }
                                    updateGradientStops(nextStops)
                                }}
                                colors={getSeriesColorPalette()}
                                showCustomColor
                                hideDropdown
                                preventPopoverClose
                                customColorValue={stop.color}
                            />
                            <LemonInput
                                className="flex-1"
                                type="number"
                                value={stop.value ?? 0}
                                onChange={(value) => {
                                    const nextStops = [...gradientStops]
                                    nextStops[index] = {
                                        ...nextStops[index],
                                        value: normalizeNumberInput(value ?? 0),
                                    }
                                    updateGradientStops(nextStops)
                                }}
                            />
                            <LemonButton
                                icon={<IconTrash />}
                                status="danger"
                                title="Remove gradient stop"
                                noPadding
                                onClick={() => {
                                    const nextStops = gradientStops.filter((_, stopIndex) => stopIndex !== index)
                                    updateGradientStops(nextStops.length ? nextStops : defaultGradientStops)
                                }}
                            />
                        </div>
                    ))}
                </div>
                <LemonButton
                    className="mt-2"
                    type="tertiary"
                    onClick={() => {
                        const sortedStops = sortGradientStops(gradientStops)
                        const lastStop = sortedStops[sortedStops.length - 1]
                        const nextValue = (lastStop?.value ?? 0) + 1
                        const nextColor = lastStop?.color ?? defaultGradientStops[0].color
                        updateGradientStops([...sortedStops, { value: nextValue, color: nextColor }])
                    }}
                    icon={<IconPlusSmall />}
                    fullWidth
                >
                    Add gradient stop
                </LemonButton>
            </div>
        </div>
    )
}
