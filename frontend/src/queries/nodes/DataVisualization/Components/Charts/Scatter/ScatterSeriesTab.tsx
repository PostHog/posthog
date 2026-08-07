import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput, LemonLabel, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { ScatterSettings } from '~/queries/schema/schema-general'

import { Column, dataVisualizationLogic } from '../../../dataVisualizationLogic'

const toColumnOption = ({ name, type }: Column): { value: string; label: JSX.Element } => ({
    value: name,
    label: (
        <div className="items-center flex-1">
            {name}
            <LemonTag className="ml-2" type="default">
                {type.name}
            </LemonTag>
        </div>
    ),
})

export const ScatterSeriesTab = (): JSX.Element => {
    const { columns, numericalColumns, responseLoading, chartSettings } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)

    const scatterSettings: ScatterSettings = chartSettings.scatter ?? {}

    const updateScatterSettings = (partial: Partial<ScatterSettings>): void => {
        updateChartSettings({
            scatter: {
                ...scatterSettings,
                ...partial,
            },
        })
    }

    const columnOptions = columns.map(toColumnOption)
    const numericalOptions = numericalColumns.map(toColumnOption)

    return (
        <div className="flex flex-col w-full p-3 gap-4">
            <div>
                <LemonLabel className="mb-1">X-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.xAxisColumn ?? null}
                    options={numericalOptions}
                    placeholder="Select a column"
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => updateScatterSettings({ xAxisColumn: value ?? undefined })}
                />
                <LemonLabel className="mt-2 mb-1">X-axis label</LemonLabel>
                <LemonInput
                    value={scatterSettings.xAxisLabel ?? ''}
                    placeholder={scatterSettings.xAxisColumn ?? 'X-axis label'}
                    onChange={(value) => updateScatterSettings({ xAxisLabel: value })}
                />
                <LemonCheckbox
                    className="mt-2"
                    label="Logarithmic scale"
                    checked={scatterSettings.xLogScale ?? false}
                    onChange={(checked) => updateScatterSettings({ xLogScale: checked })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1">Y-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.yAxisColumn ?? null}
                    options={numericalOptions}
                    placeholder="Select a column"
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    onChange={(value) => updateScatterSettings({ yAxisColumn: value ?? undefined })}
                />
                <LemonLabel className="mt-2 mb-1">Y-axis label</LemonLabel>
                <LemonInput
                    value={scatterSettings.yAxisLabel ?? ''}
                    placeholder={scatterSettings.yAxisColumn ?? 'Y-axis label'}
                    onChange={(value) => updateScatterSettings({ yAxisLabel: value })}
                />
                <LemonCheckbox
                    className="mt-2"
                    label="Logarithmic scale"
                    checked={scatterSettings.yLogScale ?? false}
                    onChange={(checked) => updateScatterSettings({ yLogScale: checked })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1" info="Shown as the tooltip title when hovering a point">
                    Point label
                </LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.labelColumn ?? null}
                    options={[{ value: null, label: 'None' }, ...columnOptions]}
                    disabledReason={responseLoading ? 'Query loading...' : undefined}
                    // null (not undefined) persists the explicit "no label" choice so auto-fill won't undo it
                    onChange={(value) => updateScatterSettings({ labelColumn: value })}
                />
            </div>
        </div>
    )
}
