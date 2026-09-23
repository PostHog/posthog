import { useActions, useValues } from 'kea'

import { LemonBanner, LemonLabel, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { BoxPlotSettings } from '~/queries/schema/schema-general'

import { Column, dataVisualizationLogic } from '../dataVisualizationLogic'
import { BOX_PLOT_STATISTICS } from './Charts/sqlBoxPlotAdapter'

const NONE_COLUMN = '__posthog_box_plot_none__'

export const BoxPlotSeriesTab = (): JSX.Element => {
    const { chartSettings, columns, numericalColumns, responseLoading } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)
    const settings = chartSettings.boxPlot ?? {}

    const updateSettings = (updates: Partial<BoxPlotSettings>): void => {
        updateChartSettings({ boxPlot: { ...settings, ...updates } })
    }

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

    const columnOptions = columns.map(toColumnOption)
    const numericalOptions = numericalColumns.map(toColumnOption)
    const optionalColumnOptions = [{ value: NONE_COLUMN, label: 'None' }, ...columnOptions]
    const disabledReason = responseLoading ? 'Query loading...' : undefined

    return (
        <div className="flex flex-col w-full p-3 gap-4">
            <LemonBanner type="info">
                Return one row per box. Calculate the minimum, percentiles, mean, and maximum in SQL.
            </LemonBanner>

            <div>
                <LemonLabel className="mb-1">X-axis</LemonLabel>
                <LemonSelect
                    className="w-full"
                    data-attr="box-plot-x-axis-column"
                    value={settings.xAxisColumn ?? NONE_COLUMN}
                    options={optionalColumnOptions}
                    disabledReason={disabledReason}
                    onChange={(value) => updateSettings({ xAxisColumn: value === NONE_COLUMN ? null : value })}
                />
                <div className="text-xs text-secondary mt-1">Optional when the query returns one row.</div>
            </div>

            <div>
                <LemonLabel className="mb-1">Series</LemonLabel>
                <LemonSelect
                    className="w-full"
                    data-attr="box-plot-series-column"
                    value={settings.seriesColumn ?? NONE_COLUMN}
                    options={optionalColumnOptions}
                    disabledReason={disabledReason}
                    onChange={(value) => updateSettings({ seriesColumn: value === NONE_COLUMN ? null : value })}
                />
                <div className="text-xs text-secondary mt-1">Optional. Each value becomes a separate series.</div>
            </div>

            <div className="flex flex-col gap-3">
                {BOX_PLOT_STATISTICS.map(({ setting, label }) => (
                    <div key={setting}>
                        <LemonLabel className="mb-1">{label}</LemonLabel>
                        <LemonSelect
                            className="w-full"
                            data-attr={`box-plot-${setting}`}
                            value={settings[setting]}
                            placeholder="Select a numeric column"
                            options={numericalOptions}
                            disabledReason={disabledReason}
                            onChange={(value) => updateSettings({ [setting]: value })}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}
