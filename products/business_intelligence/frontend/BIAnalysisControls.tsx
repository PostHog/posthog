import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { ChartDisplayType } from '~/types'

import { biEditorLogic } from './biEditorLogic'
import { getBIValuePillLabel, isDateTimeBIField } from './biEditorTypes'
import { BIShelfCard } from './components/BIShelfCard'

export function BIAnalysisControls(): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { setTopN, setTotals } = useActions(biEditorLogic)
    const dimensions = [...config.rows, ...config.columns].filter((field) => !isDateTimeBIField(field))
    const table = [ChartDisplayType.ActionsTable, ChartDisplayType.TwoDimensionalHeatmap].includes(config.chartType)
    return (
        <BIShelfCard title="Analysis">
            <div className="flex min-w-0 flex-col gap-2">
                <LemonCheckbox
                    labelClassName="text-xs"
                    label="Top N breakdown"
                    checked={!!config.topN}
                    disabledReason={!dimensions.length ? 'Add a categorical dimension first' : undefined}
                    onChange={(checked) =>
                        setTopN(
                            checked
                                ? { fieldId: dimensions[0].id, count: 10, measureIndex: 0, includeOther: true }
                                : undefined
                        )
                    }
                />
                {config.topN ? (
                    <>
                        <LemonSelect
                            size="xsmall"
                            fullWidth
                            aria-label="Top N dimension"
                            value={config.topN.fieldId}
                            options={dimensions.map((field) => ({ value: field.id, label: field.name }))}
                            onChange={(fieldId) => setTopN({ ...config.topN!, fieldId })}
                        />
                        <LemonInput
                            size="small"
                            type="number"
                            min={1}
                            max={100}
                            aria-label="Top N count"
                            value={config.topN.count}
                            onChange={(count) =>
                                setTopN({ ...config.topN!, count: Math.max(1, Math.min(100, Math.trunc(count ?? 10))) })
                            }
                        />
                        <LemonSelect
                            size="xsmall"
                            fullWidth
                            aria-label="Rank breakdown by"
                            value={config.topN.measureIndex}
                            options={
                                config.values.length
                                    ? config.values.map((value, index) => ({
                                          value: index,
                                          label: getBIValuePillLabel(value),
                                      }))
                                    : [{ value: 0, label: 'Count' }]
                            }
                            onChange={(measureIndex) => setTopN({ ...config.topN!, measureIndex })}
                        />
                        <LemonCheckbox
                            labelClassName="text-xs"
                            label='Include "Other"'
                            checked={config.topN.includeOther}
                            onChange={(includeOther) => setTopN({ ...config.topN!, includeOther })}
                        />
                        <span className="text-xs text-secondary">
                            Ranked across the full date range before table calculations.
                        </span>
                    </>
                ) : null}
                {table ? (
                    <>
                        <LemonLabel>Totals</LemonLabel>
                        <LemonCheckbox
                            labelClassName="text-xs"
                            label={
                                config.chartType === ChartDisplayType.ActionsTable ? 'Grand total' : 'Row grand totals'
                            }
                            checked={!!config.totals?.rows}
                            onChange={(rows) => setTotals({ ...config.totals, rows })}
                        />
                        {config.chartType === ChartDisplayType.TwoDimensionalHeatmap ? (
                            <LemonCheckbox
                                labelClassName="text-xs"
                                label="Column grand totals"
                                checked={!!config.totals?.columns}
                                onChange={(columns) => setTotals({ ...config.totals, columns })}
                            />
                        ) : null}
                        <LemonCheckbox
                            labelClassName="text-xs"
                            label="Subtotals"
                            checked={!!config.totals?.subtotals}
                            onChange={(subtotals) => setTotals({ ...config.totals, subtotals })}
                        />
                        {config.values.some((value) => value.tableCalculation) ? (
                            <span className="text-xs text-secondary">Table calculation cells are blank in totals.</span>
                        ) : null}
                    </>
                ) : null}
            </div>
        </BIShelfCard>
    )
}
