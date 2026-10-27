import { useState } from 'react'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { ChartSettings, YAxisSettings } from '~/queries/schema/schema-general'

import { BIChartAxis } from './BIChartAxisControls'

export function BIChartAxisModal({
    axis,
    settings,
    onSave,
    onClose,
}: {
    axis: BIChartAxis
    settings: ChartSettings
    onSave: (settings: ChartSettings) => void
    onClose: () => void
}): JSX.Element {
    const key = axis === 'right' ? 'rightYAxisSettings' : 'leftYAxisSettings'
    const [label, setLabel] = useState(axis === 'x' ? (settings.xAxisLabel ?? '') : (settings[key]?.label ?? ''))
    const [dateFormat, setDateFormat] = useState(settings.xAxisDateFormat ?? '')
    const [tickRotation, setTickRotation] = useState<number | null>(settings.xAxisTickRotation ?? null)
    const [draft, setDraft] = useState<YAxisSettings>(settings[key] ?? {})
    const [showTicks, setShowTicks] = useState(
        axis === 'x' ? (settings.showXAxisTicks ?? true) : (settings[key]?.showTicks ?? true)
    )
    return (
        <LemonModal
            isOpen
            title="Edit axis"
            onClose={onClose}
            width="28rem"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => {
                            onSave(
                                axis === 'x'
                                    ? {
                                          ...settings,
                                          xAxisLabel: label,
                                          showXAxisTicks: showTicks,
                                          xAxisDateFormat: dateFormat || undefined,
                                          xAxisTickRotation: tickRotation ?? undefined,
                                      }
                                    : { ...settings, [key]: { ...draft, label, showTicks } }
                            )
                            onClose()
                        }}
                    >
                        Save axis
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <LemonLabel htmlFor="bi-axis-label">Axis label</LemonLabel>
                <LemonInput id="bi-axis-label" value={label} onChange={setLabel} autoFocus />
                {axis !== 'x' && (
                    <>
                        <LemonLabel>Scale</LemonLabel>
                        <LemonSelect
                            aria-label="Axis scale"
                            value={draft.scale ?? 'linear'}
                            options={[
                                { value: 'linear', label: 'Linear' },
                                { value: 'logarithmic', label: 'Logarithmic' },
                            ]}
                            onChange={(scale) => setDraft({ ...draft, scale })}
                        />
                        <LemonSwitch
                            label="Begin at zero"
                            checked={draft.startAtZero ?? true}
                            onChange={(startAtZero) => setDraft({ ...draft, startAtZero })}
                        />
                    </>
                )}
                {axis === 'x' && (
                    <>
                        <LemonLabel htmlFor="bi-axis-date-format">Date format</LemonLabel>
                        <LemonInput
                            id="bi-axis-date-format"
                            value={dateFormat}
                            onChange={setDateFormat}
                            placeholder="Automatic"
                        />
                        <p className="m-0 text-xs text-secondary">
                            For date fields, use YYYY-MM-DD, MMM YYYY, or DD/MM/YYYY. Leave empty for automatic
                            formatting.
                        </p>
                        <LemonLabel>Tick label rotation</LemonLabel>
                        <LemonSelect
                            value={tickRotation}
                            onChange={setTickRotation}
                            options={[
                                { value: null, label: 'Automatic' },
                                ...[0, -45, -90, 45, 90].map((value) => ({ value, label: `${value}°` })),
                            ]}
                        />
                    </>
                )}
                <LemonSwitch label="Show tick labels" checked={showTicks} onChange={setShowTicks} />
            </div>
        </LemonModal>
    )
}
