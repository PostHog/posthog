import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { ChartOptionSections } from 'lib/components/ChartOptions/ChartOptionSections'
import { useDisplayOptions } from 'lib/components/ChartOptions/useDisplayOptions'
import { GoalLinesList } from 'lib/components/GoalLinesList'
import { PART_OF_WHOLE_DISPLAY_TYPES } from 'lib/constants'

import { ChartDisplayType } from '~/types'

import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'
import { DisplayTabPanel, DisplayTabPanels } from './DisplayTabPanels'
import { sqlDisplayOptions } from './sqlDisplayOptions'

export const DisplayTab = (): JSX.Element => {
    const { effectiveVisualizationType } = useValues(dataVisualizationLogic)
    const { goalLines, chartSettings, query } = useValues(displayLogic)
    const { addGoalLine, updateGoalLine, removeGoalLine } = useActions(displayLogic)
    const { tabs } = useDisplayOptions(sqlDisplayOptions)

    const isStackedBarChart = effectiveVisualizationType === ChartDisplayType.ActionsStackedBar
    const isBIVisualization = query.kind === 'BIVisualizationNode'
    const supportsGoalLines =
        effectiveVisualizationType !== ChartDisplayType.Metric &&
        effectiveVisualizationType !== ChartDisplayType.ScatterPlot &&
        effectiveVisualizationType !== ChartDisplayType.BoxPlot &&
        !PART_OF_WHOLE_DISPLAY_TYPES.includes(effectiveVisualizationType)

    // Each axis gets its own panel: together they hold too many settings for one.
    const panels: DisplayTabPanel[] = tabs.flatMap((tab): DisplayTabPanel[] =>
        tab.key === 'axes'
            ? tab.sections.map((section) => ({
                  key: section.key,
                  header: section.title,
                  content: <ChartOptionSections sections={[{ ...section, title: undefined }]} />,
              }))
            : [
                  {
                      key: tab.key,
                      header: tab.label,
                      content: (
                          <ChartOptionSections
                              sections={
                                  tab.sections.length === 1 ? [{ ...tab.sections[0], title: undefined }] : tab.sections
                              }
                          />
                      ),
                  },
              ]
    )
    if (supportsGoalLines) {
        panels.push({
            key: 'goals',
            header: (
                <div className="flex items-center gap-1 flex-1">
                    <span className="flex-1">{isBIVisualization ? 'Reference lines' : 'Goal lines'}</span>
                    {goalLines.length > 0 && <LemonBadge.Number status="muted" size="small" count={goalLines.length} />}
                </div>
            ),
            content: (
                <>
                    <GoalLinesList
                        allowCalculations={isBIVisualization}
                        calculationDisabledReason={
                            isStackedBarChart && chartSettings.stackBars100
                                ? 'Calculated lines are hidden on 100% stacked charts. Use a constant or turn off percentage stacking.'
                                : undefined
                        }
                        goalLines={goalLines}
                        removeGoalLine={removeGoalLine}
                        updateGoalLine={updateGoalLine}
                    />
                    <LemonButton onClick={addGoalLine} icon={<IconPlusSmall />} fullWidth>
                        {isBIVisualization ? 'Add reference line' : 'Add goal line'}
                    </LemonButton>
                    {isBIVisualization && (
                        <p className="text-xs text-secondary mb-0">
                            Calculations use returned marks on the left axis after aggregation and table calculations.
                            Per series adds a line for each color group or measure. Result limits apply.
                            {isStackedBarChart && chartSettings.stackBars100 && (
                                <span> Calculated lines are hidden on 100% stacked charts.</span>
                            )}
                        </p>
                    )}
                </>
            ),
        })
    }

    return <DisplayTabPanels defaultOpenKeys={['general']} panels={panels} />
}
