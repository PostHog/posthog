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
                                    ? { ...settings, xAxisLabel: label, showXAxisTicks: showTicks }
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
                <LemonSwitch label="Show tick labels" checked={showTicks} onChange={setShowTicks} />
            </div>
        </LemonModal>
    )
}
