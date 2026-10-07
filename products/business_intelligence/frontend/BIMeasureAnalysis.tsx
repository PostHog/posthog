import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { BI_TABLE_CALCULATIONS } from './biAnalysis'
import { biEditorLogic } from './biEditorLogic'
import { getBIValuePillLabel } from './biEditorTypes'

export function BIMeasureAnalysis({ index }: { index: number }): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { setTableCalculation } = useActions(biEditorLogic)
    const value = config.values[index]
    const calculation = value.tableCalculation
    return (
        <div className="flex min-w-0 flex-col gap-1 border-t pt-2">
            <LemonLabel className="truncate">{getBIValuePillLabel(value)}</LemonLabel>
            <LemonSelect
                size="xsmall"
                fullWidth
                aria-label={`Calculation for ${getBIValuePillLabel(value)}`}
                data-attr="bi-editor-table-calculation"
                value={calculation?.type ?? null}
                options={[{ value: null, label: 'No table calculation' }, ...BI_TABLE_CALCULATIONS]}
                onChange={(type) => setTableCalculation(index, type ? { ...calculation, type } : undefined)}
            />
            {calculation ? (
                <>
                    <LemonSelect
                        size="xsmall"
                        fullWidth
                        aria-label="Compute using"
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
                    ) : null}
                    <span className="text-xs text-secondary">
                        Ascending order within each series. Missing points stay missing.
                    </span>
                </>
            ) : null}
        </div>
    )
}
