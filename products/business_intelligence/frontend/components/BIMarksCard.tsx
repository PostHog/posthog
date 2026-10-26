import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { ChartDisplayType } from '~/types'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import { getBIFieldPillLabel, isDateTimeBIField } from 'products/business_intelligence/frontend/biEditorTypes'
import { BIShelfCard } from 'products/business_intelligence/frontend/components/BIShelfCard'

import { BIMeasureAnalysis } from '../BIMeasureAnalysis'
import { getBIChartFields } from '../biPaneConfig'
import { BIPaneControls } from '../BIPaneControls'
import { getBIScatterAxisOptions } from '../biScatter'
import { biSceneLogic } from '../biSceneLogic'

export function BIMarksCard(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { combineMeasures, setColorBy } = useActions(biEditorLogic)
    const { worksheet } = useValues(biSceneLogic)
    const { setScatterAxis } = useActions(biSceneLogic)
    const scatter = config.chartType === ChartDisplayType.ScatterPlot
    const measures = getBIScatterAxisOptions(config)

    return (
        <BIShelfCard title="Series">
            {scatter && (
                <>
                    <LemonLabel className="text-xs">X axis</LemonLabel>
                    <LemonSelect
                        fullWidth
                        size="xsmall"
                        value={worksheet.chartSettings?.xAxis?.column ?? ''}
                        options={measures}
                        onChange={(column) => setScatterAxis('x', column)}
                        data-attr="bi-scatter-x-measure"
                    />
                    <LemonLabel className="mt-2 text-xs">Y axis</LemonLabel>
                    <LemonSelect
                        fullWidth
                        size="xsmall"
                        value={worksheet.chartSettings?.yAxis?.[0]?.column ?? ''}
                        options={measures.filter((measure) => measure.value !== worksheet.chartSettings?.xAxis?.column)}
                        onChange={(column) => setScatterAxis('y', column)}
                        data-attr="bi-scatter-y-measure"
                    />
                    <p className="my-2 text-xs text-secondary">
                        {config.rows.length + config.columns.length
                            ? `One point per ${[...config.rows, ...config.columns].map(getBIFieldPillLabel).join(' × ')}. Add detail dimensions to Rows or Columns.`
                            : 'One point across all matching rows. Add dimensions to Rows or Columns to define point detail.'}
                    </p>
                </>
            )}
            <LemonLabel className="mt-2 text-xs">Color</LemonLabel>
            <LemonSelect
                value={config.colorBy === undefined ? '__automatic' : config.colorBy}
                options={[
                    { value: '__automatic', label: 'Automatic colors' },
                    { value: null, label: 'Single color' },
                    ...((scatter || getBIChartFields(config).length === 2) && !config.compareFilter?.compare
                        ? getBIChartFields(config)
                              .filter((field) => !isDateTimeBIField(field))
                              .map((field) => ({ value: field.id, label: `By ${getBIFieldPillLabel(field)}` }))
                        : []),
                ]}
                onChange={(colorBy) => setColorBy(colorBy === '__automatic' ? undefined : colorBy)}
                aria-label="Color series by"
                size="xsmall"
                fullWidth
                data-attr="bi-editor-color-by"
            />
            <span className="text-xs text-secondary">
                {scatter
                    ? 'Every shelf dimension contributes to point detail, including the color dimension.'
                    : 'Shelves define the groups. Color changes how series are distinguished.'}
            </span>
            {config.values.length === 2 && !scatter ? (
                <LemonButton
                    size="xsmall"
                    fullWidth
                    data-attr="bi-editor-combine-measures"
                    onClick={combineMeasures}
                    disabledReason={
                        config.rows.length + config.columns.length > 2
                            ? 'Use at most two dimensions for a combined chart'
                            : undefined
                    }
                >
                    Combine line + bar
                </LemonButton>
            ) : null}
            {config.values.map((_, index) => (
                <BIMeasureAnalysis key={index} index={index} />
            ))}
            <BIPaneControls />
        </BIShelfCard>
    )
}
