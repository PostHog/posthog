import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { ChartSettingsDisplay, ChartSettingsFormatting } from '~/queries/schema/schema-general'

import { biEditorLogic } from './biEditorLogic'
import { getBIValuePillLabel } from './biEditorTypes'
import { getBIMeasureSettings } from './biMeasureSettings'

export function BIMeasureSettingsModal(): JSX.Element {
    const { config, activeMeasureSettingsIndex: index } = useValues(biEditorLogic)
    const { editMeasureSettings, updateMeasureSettings } = useActions(biEditorLogic)
    const value = index !== null ? config.values[index] : undefined
    const formatting = value ? (getBIMeasureSettings(value)?.formatting ?? {}) : {}
    const display = value?.display ?? {}
    const setFormatting = (update: Partial<ChartSettingsFormatting>): void => {
        if (index !== null) {
            updateMeasureSettings(index, { formatting: { ...formatting, ...update } })
        }
    }
    const setDisplay = (update: Partial<ChartSettingsDisplay>): void => {
        if (index !== null) {
            updateMeasureSettings(index, { display: { ...display, ...update } })
        }
    }
    return (
        <LemonModal
            title="Measure display"
            isOpen={!!value}
            onClose={() => editMeasureSettings(null)}
            footer={
                <LemonButton type="primary" onClick={() => editMeasureSettings(null)}>
                    Done
                </LemonButton>
            }
        >
            {value ? (
                <div className="flex w-80 max-w-full flex-col gap-2">
                    <span className="truncate text-secondary">{getBIValuePillLabel(value)}</span>
                    <LemonLabel>Label</LemonLabel>
                    <LemonInput
                        aria-label="Measure label"
                        value={display.label ?? ''}
                        placeholder={getBIValuePillLabel(value)}
                        onChange={(label) => setDisplay({ label })}
                    />
                    <LemonLabel>Number format</LemonLabel>
                    <LemonSelect
                        fullWidth
                        aria-label="Number format"
                        value={formatting.style ?? 'number'}
                        options={[
                            { value: 'number', label: 'Number' },
                            { value: 'short', label: 'Abbreviated (1.2K)' },
                            { value: 'percent', label: 'Percent (0–1)' },
                            { value: 'none', label: 'Unformatted' },
                        ]}
                        onChange={(style) => setFormatting({ style, prefix: '', suffix: '' })}
                    />
                    <LemonLabel>Currency</LemonLabel>
                    <LemonSelect
                        fullWidth
                        aria-label="Currency"
                        value={formatting.prefix ?? ''}
                        options={[
                            { value: '', label: 'None' },
                            { value: '$', label: 'US dollar ($)' },
                            { value: '€', label: 'Euro (€)' },
                            { value: '£', label: 'British pound (£)' },
                            { value: '¥', label: 'Japanese yen (¥)' },
                            { value: 'CA$', label: 'Canadian dollar (CA$)' },
                            { value: 'A$', label: 'Australian dollar (A$)' },
                        ]}
                        onChange={(prefix) =>
                            setFormatting({
                                prefix,
                                style: 'number',
                                decimalPlaces: formatting.decimalPlaces ?? 2,
                                suffix: '',
                            })
                        }
                    />
                    <LemonLabel>Decimal places</LemonLabel>
                    <LemonInput
                        type="number"
                        aria-label="Decimal places"
                        min={0}
                        max={12}
                        value={formatting.decimalPlaces}
                        placeholder="Automatic"
                        disabledReason={
                            formatting.style === 'short'
                                ? 'Abbreviated numbers choose their precision automatically'
                                : undefined
                        }
                        onChange={(decimalPlaces) =>
                            setFormatting({
                                decimalPlaces:
                                    decimalPlaces == null || !Number.isFinite(decimalPlaces)
                                        ? undefined
                                        : Math.max(0, Math.min(12, Math.trunc(decimalPlaces))),
                            })
                        }
                    />
                    <LemonLabel>Suffix</LemonLabel>
                    <LemonInput
                        aria-label="Number suffix"
                        value={formatting.suffix ?? ''}
                        placeholder="e.g. ms"
                        onChange={(suffix) => setFormatting({ suffix })}
                    />
                    <LemonLabel>Series style</LemonLabel>
                    <LemonSelect
                        fullWidth
                        aria-label="Series style"
                        value={display.displayType ?? 'auto'}
                        options={[
                            { value: 'auto', label: 'Use chart type' },
                            { value: 'line', label: 'Line' },
                            { value: 'bar', label: 'Bar' },
                            { value: 'area', label: 'Area' },
                        ]}
                        onChange={(displayType) => setDisplay({ displayType })}
                    />
                    <LemonLabel>Axis</LemonLabel>
                    <LemonSelect
                        fullWidth
                        aria-label="Measure axis"
                        value={display.yAxisPosition ?? 'left'}
                        options={[
                            { value: 'left', label: 'Left axis' },
                            { value: 'right', label: 'Right axis' },
                        ]}
                        onChange={(yAxisPosition) => setDisplay({ yAxisPosition })}
                    />
                    <p className="m-0 text-xs text-secondary">
                        Line, bar, and area charts support mixed series and separate axes. Display settings also apply
                        when this insight is saved or added to a dashboard.
                    </p>
                </div>
            ) : null}
        </LemonModal>
    )
}
