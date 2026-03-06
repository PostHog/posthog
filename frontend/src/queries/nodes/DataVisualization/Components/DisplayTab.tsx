import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCollapse, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { GoalLinesList } from 'lib/components/GoalLinesList'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'

export const DisplayTab = (): JSX.Element => {
    const { visualizationType } = useValues(dataVisualizationLogic)
    const { goalLines, chartSettings } = useValues(displayLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine, updateChartSettings } = useActions(displayLogic)

    const isStackedBarChart = visualizationType === ChartDisplayType.ActionsStackedBar

    const renderYAxisSettings = (name: 'leftYAxisSettings' | 'rightYAxisSettings'): JSX.Element => {
        return (
            <>
                <div className="flex gap-2 items-center justify-between">
                    <span className="font-medium">Scale</span>
                    <LemonSelect
                        size="xsmall"
                        value={chartSettings[name]?.scale ?? 'linear'}
                        options={[
                            { value: 'linear', label: 'Linear' },
                            { value: 'logarithmic', label: 'Logarithmic' },
                        ]}
                        onChange={(value) => {
                            updateChartSettings({ [name]: { scale: value } })
                        }}
                    />
                </div>
                <LemonSwitch
                    className="flex-1 w-full"
                    label="Show labels"
                    checked={chartSettings[name]?.showTicks ?? true}
                    onChange={(value) => {
                        updateChartSettings({ [name]: { showTicks: value } })
                    }}
                />

                <LemonSwitch
                    className="flex-1 w-full"
                    label="Begin at zero"
                    checked={chartSettings[name]?.startAtZero ?? chartSettings.yAxisAtZero ?? true}
                    onChange={(value) => {
                        updateChartSettings({ [name]: { startAtZero: value } })
                    }}
                />
                <LemonSwitch
                    className="flex-1 w-full"
                    label="Show grid lines"
                    checked={chartSettings[name]?.showGridLines ?? true}
                    onChange={(value) => {
                        updateChartSettings({ [name]: { showGridLines: value } })
                    }}
                />
            </>
        )
    }

    return (
        <div className="flex flex-col w-full">
            <LemonCollapse
                embedded
                defaultActiveKeys={['general']}
                multiple
                panels={[
                    {
                        key: 'general',
                        header: 'General',
                        className: 'p-2 flex flex-col gap-2',
                        content: (
                            <>
                                <LemonSwitch
                                    className="flex-1 w-full"
                                    label="Show legend"
                                    checked={chartSettings.showLegend ?? false}
                                    onChange={(value) => {
                                        updateChartSettings({ showLegend: value })
                                    }}
                                />
                                <LemonSwitch
                                    className="flex-1 w-full"
                                    label="Show total row"
                                    checked={chartSettings.showTotalRow ?? true}
                                    onChange={(value) => {
                                        updateChartSettings({ showTotalRow: value })
                                    }}
                                />
                                <LemonSwitch
                                    className="flex-1 w-full"
                                    label="Show X-axis labels"
                                    checked={chartSettings.showXAxisTicks ?? true}
                                    onChange={(value) => {
                                        updateChartSettings({ showXAxisTicks: value })
                                    }}
                                />
                                <LemonSwitch
                                    className="flex-1 w-full"
                                    label="Show X-axis border"
                                    checked={chartSettings.showXAxisBorder ?? true}
                                    onChange={(value) => {
                                        updateChartSettings({ showXAxisBorder: value })
                                    }}
                                />
                                <LemonSwitch
                                    className="flex-1 w-full"
                                    label="Show Y-axis border"
                                    checked={chartSettings.showYAxisBorder ?? true}
                                    onChange={(value) => {
                                        updateChartSettings({ showYAxisBorder: value })
                                    }}
                                />
                            </>
                        ),
                    },
                    {
                        key: 'left-y-axis',
                        header: 'Left Y-axis',
                        className: 'p-2 flex flex-col gap-2',
                        content: renderYAxisSettings('leftYAxisSettings'),
                    },
                    {
                        key: 'right-y-axis',
                        header: 'Right Y-axis',
                        className: 'p-2 flex flex-col gap-2',
                        content: renderYAxisSettings('rightYAxisSettings'),
                    },
                    isStackedBarChart
                        ? {
                              key: 'stacked-bar-chart',
                              header: 'Stack bars',
                              className: 'p-2 flex flex-col gap-2',
                              content: (
                                  <LemonSwitch
                                      className="flex-1"
                                      label="Stack bars 100%"
                                      checked={chartSettings.stackBars100 ?? false}
                                      onChange={(value) => {
                                          updateChartSettings({ stackBars100: value })
                                      }}
                                  />
                              ),
                          }
                        : null,
                    {
                        key: 'goals',
                        header: (
                            <div className="flex items-center gap-1 flex-1">
                                <span className="flex-1">Goals</span>
                                {goalLines.length > 0 && (
                                    <LemonBadge.Number status="muted" size="small" count={goalLines.length} />
                                )}
                            </div>
                        ),
                        className: 'p-2',
                        content: (
                            <>
                                <GoalLinesList
                                    goalLines={goalLines}
                                    removeGoalLine={removeGoalLine}
                                    updateGoalLine={updateGoalLine}
                                />
                                <LemonButton className="mt-1" onClick={addGoalLine} icon={<IconPlusSmall />} fullWidth>
                                    Add goal line
                                </LemonButton>
                            </>
                        ),
                    },
                ]}
            />
        </div>
    )
}
