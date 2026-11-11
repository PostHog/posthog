import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { BI_TABLE_CALCULATIONS } from './biAnalysis'
import { biEditorLogic } from './biEditorLogic'
import { getBIValuePillLabel } from './biEditorTypes'
import { getBIMissingDatesDisabledReason } from './biTimeSeries'

export function BIMeasureAnalysis({ index }: { index: number }): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { setTableCalculation, editMeasureSettings, updateMeasureSettings } = useActions(biEditorLogic)
    const value = config.values[index]
    const calculation = value.tableCalculation
    const missingDates = getBIMissingDatesDisabledReason(config) ? undefined : config.missingDates
    return (
        <div className="flex min-w-0 flex-col gap-1 border-t pt-2">
            <LemonLabel className="truncate">{getBIValuePillLabel(value)}</LemonLabel>
            <div className="flex flex-wrap gap-1">
                <LemonSelect
                    size="xsmall"
                    aria-label={`Series style for ${getBIValuePillLabel(value)}`}
                    value={value.display?.displayType ?? 'auto'}
                    options={[
                        { value: 'auto', label: 'Chart default' },
                        { value: 'line', label: 'Line' },
                        { value: 'bar', label: 'Bar' },
                        { value: 'area', label: 'Area' },
                    ]}
                    onChange={(displayType) =>
                        updateMeasureSettings(index, { display: { ...value.display, displayType } })
                    }
                />
                <LemonSelect
                    size="xsmall"
                    aria-label={`Axis for ${getBIValuePillLabel(value)}`}
                    value={value.display?.yAxisPosition ?? 'left'}
                    options={[
                        { value: 'left', label: 'Left axis' },
                        { value: 'right', label: 'Right axis' },
                    ]}
                    onChange={(yAxisPosition) =>
                        updateMeasureSettings(index, { display: { ...value.display, yAxisPosition } })
                    }
                />
            </div>
            <LemonSelect
                size="xsmall"
                fullWidth
                aria-label={`Calculation for ${getBIValuePillLabel(value)}`}
                data-attr="bi-editor-table-calculation"
                value={calculation?.type ?? null}
                options={[{ value: null, label: 'No table calculation' }, ...BI_TABLE_CALCULATIONS]}
                onChange={(type) => setTableCalculation(index, type ? { ...calculation, type } : undefined)}
            />
            <LemonButton
                size="xsmall"
                type="tertiary"
                data-attr="bi-editor-measure-display"
                onClick={() => editMeasureSettings(index)}
            >
                Format and display
            </LemonButton>
            {calculation ? (
                <>
                    <LemonSelect
                        size="xsmall"
                        fullWidth
                        aria-label="Compute using"
                        tooltip="Traverse this dimension in ascending order. Other dimensions define separate groups; Entire table uses one group."
                        value={calculation.computeUsing ?? null}
                        options={[
                            { value: null, label: 'Automatic (date first)' },
                            { value: 'table', label: 'Entire table' },
                            ...[...config.rows, ...config.columns].map((field) => ({
                                value: field.id,
                                label: field.name,
                            })),
                        ]}
                        onChange={(computeUsing) =>
                            setTableCalculation(index, { ...calculation, computeUsing: computeUsing ?? undefined })
                        }
                    />
                    {calculation.type === 'moving_average' ? (
                        <>
                            <LemonInput
                                type="number"
                                size="small"
                                min={1}
                                max={1000}
                                value={calculation.window ?? 3}
                                aria-label="Moving average points"
                                suffix={<span>points</span>}
                                onChange={(window) =>
                                    setTableCalculation(index, {
                                        ...calculation,
                                        window: Math.max(1, Math.min(1000, Math.trunc(window ?? 3))),
                                    })
                                }
                            />
                            <LemonCheckbox
                                label="Require a full window"
                                labelClassName="text-xs"
                                data-attr="bi-editor-moving-average-full-window"
                                checked={!!calculation.requireFullWindow}
                                onChange={(requireFullWindow) =>
                                    setTableCalculation(index, { ...calculation, requireFullWindow })
                                }
                            />
                            <span className="text-xs text-secondary">
                                Trailing {calculation.window ?? 3} points, including the current point.
                                {calculation.computeUsing === 'table'
                                    ? ' Traverses the entire table.'
                                    : ' Other dimensions define separate series.'}
                                {calculation.requireFullWindow
                                    ? ' Blank until every point in the window has a value.'
                                    : ' Partial windows use the available values; gaps are excluded from the average.'}
                            </span>
                        </>
                    ) : null}
                    <span className="text-xs text-secondary">
                        Calculated after aggregation, before the result limit. Ascending order.{' '}
                        {missingDates === 'zero'
                            ? 'Empty date buckets contribute zero.'
                            : missingDates === 'gap'
                              ? 'Empty date buckets occupy a point in the window.'
                              : 'Only observed points occupy a point in the window.'}
                    </span>
                </>
            ) : null}
        </div>
    )
}
