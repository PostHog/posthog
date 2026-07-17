import { useActions, useValues } from 'kea'

import { LemonLabel, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { ScatterSettings } from '~/queries/schema/schema-general'

import { Column, dataVisualizationLogic } from '../../../dataVisualizationLogic'

const columnOption = ({ name, type }: Column): { value: string; label: JSX.Element } => ({
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

const NONE_OPTION = { value: null, label: <span>None</span> }

export const ScatterSeriesTab = (): JSX.Element => {
    const { columns, numericalColumns, responseLoading, chartSettings } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)

    const scatterSettings = chartSettings.scatter ?? ({} as ScatterSettings)

    const updateScatterSettings = (partial: Partial<ScatterSettings>): void => {
        updateChartSettings({
            scatter: {
                ...scatterSettings,
                ...partial,
            },
        })
    }

    const xColumns = columns.filter(
        (column) => column.type.name === 'DATE' || column.type.name === 'DATETIME' || column.type.isNumerical
    )
    const disabledReason = responseLoading ? 'Query loading...' : undefined

    return (
        <div className="flex flex-col w-full p-3 gap-4">
            <div>
                <LemonLabel className="mb-1">X-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.xAxisColumn ?? null}
                    options={xColumns.map(columnOption)}
                    placeholder="Date or numeric column"
                    disabledReason={disabledReason}
                    onChange={(value) => updateScatterSettings({ xAxisColumn: value ?? undefined })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1">Y-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.yAxisColumn ?? null}
                    options={numericalColumns.map(columnOption)}
                    placeholder="Numeric column"
                    disabledReason={disabledReason}
                    onChange={(value) => updateScatterSettings({ yAxisColumn: value ?? undefined })}
                />
                <LemonSwitch
                    className="mt-2"
                    label="Logarithmic y-axis"
                    checked={scatterSettings.yAxisScale === 'logarithmic'}
                    onChange={(checked) => updateScatterSettings({ yAxisScale: checked ? 'logarithmic' : 'linear' })}
                />
            </div>

            <div>
                <LemonLabel className="mb-1" info="Rows are grouped by this column's value; each group gets a color.">
                    Color by
                </LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.colorByColumn || null}
                    options={[NONE_OPTION, ...columns.map(columnOption)]}
                    disabledReason={disabledReason}
                    // '' (not null) marks a cleared column: the insight save path drops null
                    // fields, which would let auto-fill resurrect the cleared value on reload.
                    onChange={(value) => updateScatterSettings({ colorByColumn: value ?? '' })}
                />
            </div>

            <div>
                <LemonLabel
                    className="mb-1"
                    info="When you click a dot, this column's value links to the person's profile in the row details."
                >
                    Person column
                </LemonLabel>
                <LemonSelect
                    className="w-full"
                    value={scatterSettings.personColumn || null}
                    options={[NONE_OPTION, ...columns.map(columnOption)]}
                    disabledReason={disabledReason}
                    onChange={(value) => updateScatterSettings({ personColumn: value ?? '' })}
                />
            </div>
        </div>
    )
}
