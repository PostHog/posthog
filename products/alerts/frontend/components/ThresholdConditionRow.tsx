import { Group } from 'kea-forms'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import type { AlertSuggestThresholdsResponseApi } from 'products/alerts/frontend/generated/api.schemas'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import {
    fractionToPercentInput,
    inputToStoredBound,
    thresholdForConditionChange,
    thresholdForUnitChange,
} from 'products/alerts/frontend/logic/thresholdPercent'
import { isFunnelsAlertConfig } from 'products/alerts/frontend/types'

export interface ThresholdConditionRowProps {
    alertForm: AlertFormType
    thresholdBoundsFormError?: string
    isNonTimeSeriesDisplay: boolean
    /** Whether relative conditions (increase/decrease by) are pickable. False for steps funnels;
     *  true for trends, HogQL last/first row, and trends funnels. */
    supportsRelativeConditions: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
    /** Candidate bounds to pick from with one click. Shown only for the "has value" condition. */
    thresholdSuggestions?: AlertSuggestThresholdsResponseApi | null
    onApplyThresholdSuggestion?: (direction: 'upper' | 'lower', value: number) => void
}

function ThresholdSuggestionButtons({
    direction,
    suggestions,
    currentValue,
    onApply,
}: {
    direction: 'upper' | 'lower'
    suggestions: AlertSuggestThresholdsResponseApi
    currentValue: number | null | undefined
    onApply: (direction: 'upper' | 'lower', value: number) => void
}): JSX.Element | null {
    const candidates = suggestions[direction]
    if (candidates.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-1 pl-[5.5rem]">
            {candidates.map((candidate) => {
                const isRecommended =
                    suggestions.recommended_direction === direction && suggestions.recommended_value === candidate.value
                return (
                    <LemonButton
                        key={candidate.value}
                        size="xsmall"
                        type="secondary"
                        active={currentValue === candidate.value}
                        icon={isRecommended ? <IconSparkles /> : undefined}
                        tooltip={isRecommended ? `${candidate.description}. Suggested default.` : candidate.description}
                        data-attr={`alertForm-${direction}-threshold-suggestion`}
                        onClick={() => onApply(direction, candidate.value)}
                    >
                        {humanFriendlyNumber(candidate.value)}
                    </LemonButton>
                )
            })}
        </div>
    )
}

/** Relative conditions (increase/decrease by) need a time series, so they're disabled for non-time-series
 *  trends and for HogQL any-row mode. Mirrors the gating in AlertDefinitionSection. */
function relativeConditionDisabledReason(isNonTimeSeriesDisplay: boolean, isAnyRowHogQL: boolean): string | undefined {
    if (isNonTimeSeriesDisplay) {
        return 'This condition is only supported for time series trends'
    }
    if (isAnyRowHogQL) {
        return "Rows in any-row mode aren't a time series — switch to 'the latest value' for relative conditions"
    }
    return undefined
}

interface ConditionOption {
    label: string
    value: AlertConditionType
    disabledReason?: string
}

const CONDITION_OPTIONS = (disabledReason?: string): ConditionOption[] => [
    { label: 'has value', value: AlertConditionType.ABSOLUTE_VALUE },
    { label: 'increases by', value: AlertConditionType.RELATIVE_INCREASE, disabledReason },
    { label: 'decreases by', value: AlertConditionType.RELATIVE_DECREASE, disabledReason },
]

const UNIT_OPTIONS = [
    { value: InsightThresholdType.PERCENTAGE, label: '%', tooltip: 'Percent' },
    { value: InsightThresholdType.ABSOLUTE, label: '#', tooltip: 'Absolute number' },
]

/** The threshold + condition config, laid out as separate labeled rows. */
export function ThresholdConditionRow({
    alertForm,
    thresholdBoundsFormError,
    isNonTimeSeriesDisplay,
    supportsRelativeConditions,
    onSetAlertFormValue,
    thresholdSuggestions,
    onApplyThresholdSuggestion,
}: ThresholdConditionRowProps): JSX.Element {
    const isFunnelAlert = isFunnelsAlertConfig(alertForm.config)
    const isAnyRowHogQL =
        !!alertForm.config && alertForm.config.type === 'HogQLAlertConfig' && alertForm.config.evaluation === 'any_row'
    const disabledReason = relativeConditionDisabledReason(isNonTimeSeriesDisplay, isAnyRowHogQL)
    const isRelative = alertForm.condition?.type !== AlertConditionType.ABSOLUTE_VALUE
    const showSuggestions = !isRelative && !!thresholdSuggestions && !!onApplyThresholdSuggestion

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <span className="text-sm text-muted shrink-0 w-20">Fire when</span>
                <Group name={['condition']}>
                    <LemonField name="type">
                        {({ value, onChange }) => (
                            <LemonSelect
                                fullWidth
                                className="w-40 shrink-0"
                                data-attr="alertForm-condition"
                                value={value}
                                onChange={(newType) => {
                                    onChange(newType)
                                    const configuration = alertForm.threshold.configuration
                                    const nextConfiguration = thresholdForConditionChange(
                                        configuration,
                                        newType,
                                        isFunnelAlert
                                    )
                                    if (nextConfiguration === configuration) {
                                        return
                                    }
                                    onSetAlertFormValue('threshold', {
                                        configuration: nextConfiguration,
                                    })
                                }}
                                options={
                                    supportsRelativeConditions
                                        ? CONDITION_OPTIONS(disabledReason)
                                        : CONDITION_OPTIONS(undefined).filter(
                                              (o) => o.value === AlertConditionType.ABSOLUTE_VALUE
                                          )
                                }
                            />
                        )}
                    </LemonField>
                </Group>
                {!isFunnelAlert && isRelative && (
                    <LemonSegmentedButton
                        size="small"
                        value={alertForm.threshold.configuration.type}
                        options={UNIT_OPTIONS}
                        onChange={(newType) =>
                            onSetAlertFormValue('threshold', {
                                configuration: thresholdForUnitChange(alertForm.threshold.configuration, newType),
                            })
                        }
                    />
                )}
            </div>

            <div className="space-y-2">
                <div className="flex items-center gap-2">
                    <label className="text-sm text-muted shrink-0 w-20" htmlFor="alertForm-lower-threshold">
                        Less than
                    </label>
                    <LemonField name="lower">
                        <LemonInput
                            type="number"
                            min={isRelative ? 0 : undefined}
                            className="w-32"
                            status={thresholdBoundsFormError ? 'danger' : 'default'}
                            data-attr="alertForm-lower-threshold"
                            suffix={isFunnelAlert ? <span aria-label="percent">%</span> : undefined}
                            value={
                                alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                                    ? fractionToPercentInput(alertForm.threshold.configuration.bounds?.lower)
                                    : alertForm.threshold.configuration.bounds?.lower
                            }
                            onChange={(value) =>
                                onSetAlertFormValue('threshold', {
                                    configuration: {
                                        type: alertForm.threshold.configuration.type,
                                        bounds: {
                                            ...alertForm.threshold.configuration.bounds,
                                            lower: inputToStoredBound(value, alertForm.threshold.configuration.type),
                                        },
                                    },
                                })
                            }
                        />
                    </LemonField>
                </div>
                {showSuggestions && (
                    <ThresholdSuggestionButtons
                        direction="lower"
                        suggestions={thresholdSuggestions}
                        currentValue={alertForm.threshold.configuration.bounds?.lower}
                        onApply={onApplyThresholdSuggestion}
                    />
                )}
                <div className="flex items-center gap-2">
                    <label className="text-sm text-muted shrink-0 w-20" htmlFor="alertForm-upper-threshold">
                        More than
                    </label>
                    <LemonField name="upper">
                        <LemonInput
                            type="number"
                            min={isRelative ? 0 : undefined}
                            className="w-32"
                            status={thresholdBoundsFormError ? 'danger' : 'default'}
                            data-attr="alertForm-upper-threshold"
                            suffix={isFunnelAlert ? <span aria-label="percent">%</span> : undefined}
                            value={
                                alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                                    ? fractionToPercentInput(alertForm.threshold.configuration.bounds?.upper)
                                    : alertForm.threshold.configuration.bounds?.upper
                            }
                            onChange={(value) =>
                                onSetAlertFormValue('threshold', {
                                    configuration: {
                                        type: alertForm.threshold.configuration.type,
                                        bounds: {
                                            ...alertForm.threshold.configuration.bounds,
                                            upper: inputToStoredBound(value, alertForm.threshold.configuration.type),
                                        },
                                    },
                                })
                            }
                        />
                    </LemonField>
                </div>
                {showSuggestions && (
                    <ThresholdSuggestionButtons
                        direction="upper"
                        suggestions={thresholdSuggestions}
                        currentValue={alertForm.threshold.configuration.bounds?.upper}
                        onApply={onApplyThresholdSuggestion}
                    />
                )}
                <p
                    className={
                        thresholdBoundsFormError
                            ? 'm-0 min-h-10 pl-[5.5rem] text-xs text-danger'
                            : 'm-0 min-h-10 pl-[5.5rem] text-xs text-secondary'
                    }
                >
                    {thresholdBoundsFormError ?? 'Enter a value in either field.'}
                </p>
            </div>
        </div>
    )
}
