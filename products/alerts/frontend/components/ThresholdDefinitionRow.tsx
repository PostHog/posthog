import { Group } from 'kea-forms'

import { LemonBanner, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertDefinitionRow } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertFormType } from 'products/alerts/frontend/logic/alertFormLogic'
import {
    fractionToPercentInput,
    inputToStoredBound,
    thresholdForConditionChange,
} from 'products/alerts/frontend/logic/thresholdPercent'
import { isAnyRowHogQLConfig, isFunnelsAlertConfig } from 'products/alerts/frontend/types'

export interface ThresholdRowRenderProps {
    alertForm: AlertFormType
    thresholdBoundsFormError?: string
    isNonTimeSeriesDisplay: boolean
    supportsRelativeConditions: boolean
    onSetAlertFormValue: <K extends keyof AlertFormType>(key: K, value: AlertFormType[K]) => void
}

export function ThresholdDefinitionRow({
    alertForm,
    thresholdBoundsFormError,
    isNonTimeSeriesDisplay,
    supportsRelativeConditions,
    onSetAlertFormValue,
}: ThresholdRowRenderProps): JSX.Element {
    const isFunnelAlert = isFunnelsAlertConfig(alertForm.config)
    const relativeConditionDisabledReason =
        (isNonTimeSeriesDisplay && 'This condition is only supported for time series trends') ||
        (isAnyRowHogQLConfig(alertForm.config) &&
            "Rows in any-row mode aren't a time series. Switch to 'the latest value' for relative conditions")

    return (
        <div className="space-y-2">
            {thresholdBoundsFormError ? <LemonBanner type="error">{thresholdBoundsFormError}</LemonBanner> : null}
            <AlertDefinitionRow>
                {supportsRelativeConditions && (
                    <Group name={['condition']}>
                        <LemonField name="type">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    fullWidth
                                    className="w-40"
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
                                        onSetAlertFormValue('threshold', { configuration: nextConfiguration })
                                    }}
                                    options={[
                                        { label: 'has value', value: AlertConditionType.ABSOLUTE_VALUE },
                                        {
                                            label: 'increases by',
                                            value: AlertConditionType.RELATIVE_INCREASE,
                                            disabledReason: relativeConditionDisabledReason,
                                        },
                                        {
                                            label: 'decreases by',
                                            value: AlertConditionType.RELATIVE_DECREASE,
                                            disabledReason: relativeConditionDisabledReason,
                                        },
                                    ]}
                                />
                            )}
                        </LemonField>
                    </Group>
                )}
                <div>less than</div>
                <LemonField name="lower">
                    <LemonInput
                        type="number"
                        min={alertForm.condition.type === AlertConditionType.ABSOLUTE_VALUE ? undefined : 0}
                        className="w-30"
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
                <div>or more than</div>
                <LemonField name="upper">
                    <LemonInput
                        type="number"
                        min={alertForm.condition.type === AlertConditionType.ABSOLUTE_VALUE ? undefined : 0}
                        className="w-30"
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
                {/* Funnels always compare as a percentage of the prior period, so their unit is fixed. */}
                {!isFunnelAlert && alertForm.condition.type !== AlertConditionType.ABSOLUTE_VALUE && (
                    <Group name={['threshold', 'configuration']}>
                        <LemonField name="type">
                            <LemonSegmentedButton
                                options={[
                                    { value: InsightThresholdType.PERCENTAGE, label: '%', tooltip: 'Percent' },
                                    { value: InsightThresholdType.ABSOLUTE, label: '#', tooltip: 'Absolute number' },
                                ]}
                            />
                        </LemonField>
                    </Group>
                )}
            </AlertDefinitionRow>
        </div>
    )
}
