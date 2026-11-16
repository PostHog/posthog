import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { ForecastSideRule } from '~/queries/schema/schema-general'

import {
    DEFAULT_FORECAST_LEVELS,
    FORECAST_LEVELS,
    ForecastSide,
    forecastLevelCoverage,
    formatForecastLevel,
    sideRuleHasCondition,
} from '../logic/forecastRules'

const SIDE_COPY: Record<ForecastSide, { toggle: string; direction: string; relativeTooltip: string }> = {
    above: {
        toggle: 'Fire on spikes',
        direction: 'higher',
        relativeTooltip: 'How far above the expected value the value must be. 100% means at least double.',
    },
    below: {
        toggle: 'Fire on drops',
        direction: 'lower',
        relativeTooltip: 'How far below the expected value the value must be. 50% means at most half.',
    },
}

function FieldLabel({ text, tooltip }: { text: string; tooltip: string }): JSX.Element {
    return (
        <label className="text-xs font-semibold text-secondary mb-1 flex items-center gap-1">
            {text}
            <Tooltip title={tooltip}>
                <IconInfo className="text-muted text-base" />
            </Tooltip>
        </label>
    )
}

function describeSideRule(side: ForecastSide, rule: ForecastSideRule): string {
    const { direction } = SIDE_COPY[side]
    const conditions: string[] = []
    if (rule.quantile != null) {
        conditions.push(
            `${direction} than the model expects ${forecastLevelCoverage(side, rule.quantile)} times in 100`
        )
    }
    if (rule.min_relative_change != null) {
        conditions.push(`at least ${toPercent(rule.min_relative_change)}% ${direction} than expected`)
    }
    if (rule.min_absolute_change != null) {
        conditions.push(`at least ${rule.min_absolute_change} ${direction} than expected`)
    }
    return `Fires when the value is ${conditions.join(', and ')}.`
}

// The same rules the API applies on save, shown before the author gets that far.
function sideRuleError(side: ForecastSide, rule: ForecastSideRule): string | null {
    if (!sideRuleHasCondition(rule)) {
        return 'Pick a forecast level or set a minimum change, or turn this side off.'
    }
    if (side === 'below' && rule.min_relative_change != null && rule.min_relative_change > 1) {
        return 'A value cannot be more than 100% below expected.'
    }
    return null
}

// Rounded so 0.29 shows as 29, not 28.999999999999996.
function toPercent(fraction: number): number {
    return Math.round(fraction * 10000) / 100
}

function positiveOrUndefined(value: number | undefined): number | undefined {
    return value != null && Number.isFinite(value) && value > 0 ? value : undefined
}

export function ForecastSideRuleFields({
    side,
    rule,
    onChange,
    turnOffDisabledReason,
}: {
    side: ForecastSide
    /** Undefined when the side is turned off. */
    rule: ForecastSideRule | undefined
    onChange: (rule: ForecastSideRule | undefined) => void
    turnOffDisabledReason?: string
}): JSX.Element {
    const copy = SIDE_COPY[side]
    const error = rule ? sideRuleError(side, rule) : null
    const update = (changes: Partial<ForecastSideRule>): void => {
        const next = { ...rule, ...changes }
        onChange(
            Object.fromEntries(Object.entries(next).filter(([, value]) => value !== undefined)) as ForecastSideRule
        )
    }

    return (
        <div className="border rounded p-3 space-y-3">
            <LemonCheckbox
                data-attr={`alertForm-detector-forecast-${side}-enabled`}
                checked={!!rule}
                label={copy.toggle}
                disabledReason={rule ? turnOffDisabledReason : undefined}
                onChange={(checked) => onChange(checked ? { quantile: DEFAULT_FORECAST_LEVELS[side] } : undefined)}
            />
            {rule && (
                <>
                    <div>
                        <FieldLabel
                            text="Forecast level"
                            tooltip="The forecast gives a range of likely values. A level further from the middle fires less often. Pick none to fire on the minimum change alone."
                        />
                        <LemonSelect<number | null>
                            data-attr={`alertForm-detector-forecast-${side}-level`}
                            value={rule.quantile ?? null}
                            onChange={(quantile) => update({ quantile: quantile ?? undefined })}
                            options={[
                                { value: null, label: 'None' },
                                ...FORECAST_LEVELS[side].map((quantile) => ({
                                    value: quantile,
                                    label:
                                        quantile === DEFAULT_FORECAST_LEVELS[side]
                                            ? `${formatForecastLevel(quantile)} (default)`
                                            : formatForecastLevel(quantile),
                                })),
                            ]}
                            fullWidth
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <FieldLabel text="Minimum change" tooltip={copy.relativeTooltip} />
                            <LemonInput
                                aria-label={`Minimum change ${side === 'above' ? 'above' : 'below'} expected, in percent`}
                                data-attr={`alertForm-detector-forecast-${side}-min-relative`}
                                type="number"
                                min={0}
                                max={side === 'below' ? 100 : undefined}
                                step={5}
                                placeholder="Any"
                                suffix={<span>%</span>}
                                value={
                                    rule.min_relative_change != null ? toPercent(rule.min_relative_change) : undefined
                                }
                                onChange={(val) => {
                                    const percent = positiveOrUndefined(val)
                                    update({ min_relative_change: percent != null ? percent / 100 : undefined })
                                }}
                            />
                        </div>
                        <div>
                            <FieldLabel
                                text="Minimum difference"
                                tooltip="How far the value must be from the expected value, in the insight's units."
                            />
                            <LemonInput
                                aria-label={`Minimum difference ${side === 'above' ? 'above' : 'below'} expected`}
                                data-attr={`alertForm-detector-forecast-${side}-min-absolute`}
                                type="number"
                                min={0}
                                placeholder="Any"
                                value={rule.min_absolute_change}
                                onChange={(val) => update({ min_absolute_change: positiveOrUndefined(val) })}
                            />
                        </div>
                    </div>
                    {error ? (
                        <p className="text-xs text-danger m-0">{error}</p>
                    ) : (
                        <p className="text-xs text-muted m-0">{describeSideRule(side, rule)}</p>
                    )}
                </>
            )}
        </div>
    )
}
