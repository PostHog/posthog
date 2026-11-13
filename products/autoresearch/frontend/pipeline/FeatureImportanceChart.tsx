import { ReactNode } from 'react'

import { LemonCollapse, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { FeatureDirectionEnumApi, FeatureImportanceApi, ModelExplanationFieldApi } from '../generated/api.schemas'
import { DOMINANT_DRIVER_RATIO, dominantDriver } from '../modelQuality'

const VISIBLE_DRIVERS = 5

function DriverRow({
    feature: f,
    maxImportance,
    isNew,
}: {
    feature: FeatureImportanceApi
    maxImportance: number
    isNew: boolean
}): JSX.Element {
    const isNegative = f.direction === FeatureDirectionEnumApi.Negative
    const color = isNegative ? 'var(--danger)' : 'var(--success)'
    const effect = isNegative ? 'Lowers' : 'Raises'
    return (
        <div className="flex items-center gap-2 text-sm">
            <div className="w-48 shrink-0 flex items-center gap-1 min-w-0">
                <span className="truncate font-mono text-xs" title={f.name}>
                    <span style={{ color }}>● </span>
                    {f.name}
                </span>
                {isNew && (
                    <Tooltip title="Not in the champion's top drivers">
                        <LemonTag type="highlight" size="small" className="shrink-0">
                            New
                        </LemonTag>
                    </Tooltip>
                )}
            </div>
            <div className="flex-1 rounded h-4 overflow-hidden" style={{ backgroundColor: 'var(--border)' }}>
                <Tooltip title={`${effect} the prediction · importance ${f.importance.toFixed(3)}`}>
                    <div
                        className="h-full rounded"
                        style={{
                            width: `${maxImportance > 0 ? Math.max(2, (f.importance / maxImportance) * 100) : 2}%`,
                            backgroundColor: color,
                        }}
                    />
                </Tooltip>
            </div>
        </div>
    )
}

/** A model's top feature drivers, as importance bars relative to the strongest feature. */
export function FeatureImportanceChart({
    explanation,
    header = 'Top feature drivers',
    addedFeatures = [],
    droppedFeatures = [],
}: {
    explanation: ModelExplanationFieldApi
    header?: ReactNode
    /** Top drivers to tag as new, because the champion's top drivers do not include them. */
    addedFeatures?: string[]
    /** Champion top drivers that this model's top drivers do not include. */
    droppedFeatures?: string[]
}): JSX.Element {
    const features = explanation.top_features ?? []
    // Gain has no fixed scale, so bars are relative to the strongest feature.
    const maxImportance = Math.max(0, ...features.map((f) => f.importance))
    const dominant = dominantDriver(features)
    const rows = (list: FeatureImportanceApi[]): JSX.Element => (
        <div className="space-y-1">
            {list.map((f) => (
                <DriverRow
                    key={f.name}
                    feature={f}
                    maxImportance={maxImportance}
                    isNew={addedFeatures.includes(f.name)}
                />
            ))}
        </div>
    )
    const content =
        features.length === 0 ? (
            <div className="text-xs text-muted">No feature drivers recorded for this model.</div>
        ) : (
            <div className="space-y-2">
                {dominant && (
                    <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                        <LemonTag type="default" size="small">
                            Mostly one signal
                        </LemonTag>
                        <span>
                            <span className="font-mono">{dominant}</span> carries most of the prediction. It is at least{' '}
                            {DOMINANT_DRIVER_RATIO} times as important as the next feature.
                        </span>
                    </div>
                )}
                <div className="text-xs text-muted">
                    <span style={{ color: 'var(--success)' }}>● raises</span>{' '}
                    <span style={{ color: 'var(--danger)' }}>● lowers</span> the prediction · bars relative to the
                    strongest feature
                </div>
                {rows(features.slice(0, VISIBLE_DRIVERS))}
                {features.length > VISIBLE_DRIVERS && (
                    <LemonCollapse
                        embedded
                        size="xsmall"
                        panels={[
                            {
                                key: 'rest',
                                header: `Show all ${features.length}`,
                                content: rows(features.slice(VISIBLE_DRIVERS)),
                            },
                        ]}
                    />
                )}
                {droppedFeatures.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                        Champion top drivers not in this list:
                        {droppedFeatures.map((name) => (
                            <LemonTag key={name} type="muted" size="small" className="font-mono">
                                {name}
                            </LemonTag>
                        ))}
                    </div>
                )}
                {explanation.method && (
                    <LemonCollapse
                        embedded
                        size="xsmall"
                        panels={[
                            {
                                key: 'method',
                                header: 'How this was measured',
                                content: <div className="text-xs text-muted">{explanation.method}</div>,
                            },
                        ]}
                    />
                )}
                {explanation.note && <div className="text-xs text-muted italic">{explanation.note}</div>}
            </div>
        )
    return <LemonCollapse size="small" defaultActiveKey="features" panels={[{ key: 'features', header, content }]} />
}
