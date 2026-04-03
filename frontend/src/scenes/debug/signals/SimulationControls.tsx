import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { DEFAULT_CONFIG, SimConfig } from './types'

export function SimulationControls({
    config,
    onChange,
}: {
    config: SimConfig
    onChange: (config: SimConfig) => void
}): JSX.Element {
    const [collapsed, setCollapsed] = useState(true)

    const sliders: { key: keyof SimConfig; label: string; min: number; max: number; step: number }[] = [
        { key: 'repulsion', label: 'Repulsion', min: 0, max: 1000, step: 10 },
        { key: 'springK', label: 'Spring strength', min: 0, max: 0.16, step: 0.005 },
        { key: 'springLength', label: 'Spring length', min: 0, max: 400, step: 5 },
        { key: 'centerGravity', label: 'Center pull', min: 0, max: 0.07, step: 0.001 },
        { key: 'damping', label: 'Damping', min: 0, max: 1, step: 0.01 },
        { key: 'collideRadius', label: 'Collide radius', min: 0, max: 170, step: 5 },
    ]

    return (
        <div
            className="absolute bottom-3 right-3 z-20 rounded-md bg-surface-primary text-[13px] select-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                border: '1px solid var(--border)',
                boxShadow: 'var(--shadow-elevation-3000)',
                width: collapsed ? 'auto' : 260,
            }}
        >
            <div
                className="flex items-center justify-between px-3 py-1.5 cursor-pointer gap-2"
                onClick={() => setCollapsed((c) => !c)}
            >
                <span className="font-semibold text-xs text-muted uppercase tracking-wide">Physics</span>
                <span className="text-muted text-xs">{collapsed ? '▲' : '▼'}</span>
            </div>
            {!collapsed && (
                <div className="px-3 pb-3 space-y-3 border-t pt-2">
                    {sliders.map(({ key, label, min, max, step }) => (
                        <div key={key}>
                            <div className="flex justify-between text-xs mb-1">
                                <span className="text-muted">{label}</span>
                                <span className="font-mono tabular-nums">
                                    {config[key] % 1 === 0 ? config[key] : config[key].toFixed(step < 0.01 ? 3 : 2)}
                                </span>
                            </div>
                            <LemonSlider
                                min={min}
                                max={max}
                                step={step}
                                value={config[key]}
                                onChange={(v) => onChange({ ...config, [key]: v })}
                            />
                        </div>
                    ))}
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        fullWidth
                        center
                        onClick={() => onChange({ ...DEFAULT_CONFIG })}
                    >
                        Reset defaults
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
