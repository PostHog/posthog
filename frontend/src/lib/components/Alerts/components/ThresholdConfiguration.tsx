import { Group } from 'kea-forms'

import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'

import { AlertFormType } from '../alertFormLogic'

export interface ThresholdConfigurationProps {
    alertForm: AlertFormType
    setAlertFormValue: (key: string, value: any) => void
}

export function ThresholdConfiguration({ alertForm, setAlertFormValue }: ThresholdConfigurationProps): JSX.Element {
    return (
        <div className="flex gap-4 items-center">
            <div>less than</div>
            <LemonField name="lower">
                <LemonInput
                    type="number"
                    className="w-30"
                    data-attr="alertForm-lower-threshold"
                    value={
                        alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE &&
                        alertForm.threshold.configuration.bounds?.lower
                            ? alertForm.threshold.configuration.bounds?.lower * 100
                            : alertForm.threshold.configuration.bounds?.lower
                    }
                    onChange={(value) =>
                        setAlertFormValue('threshold', {
                            configuration: {
                                type: alertForm.threshold.configuration.type,
                                bounds: {
                                    ...alertForm.threshold.configuration.bounds,
                                    lower:
                                        value &&
                                        alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                                            ? value / 100
                                            : value,
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
                    className="w-30"
                    data-attr="alertForm-upper-threshold"
                    value={
                        alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE &&
                        alertForm.threshold.configuration.bounds?.upper
                            ? alertForm.threshold.configuration.bounds?.upper * 100
                            : alertForm.threshold.configuration.bounds?.upper
                    }
                    onChange={(value) =>
                        setAlertFormValue('threshold', {
                            configuration: {
                                type: alertForm.threshold.configuration.type,
                                bounds: {
                                    ...alertForm.threshold.configuration.bounds,
                                    upper:
                                        value &&
                                        alertForm.threshold.configuration.type === InsightThresholdType.PERCENTAGE
                                            ? value / 100
                                            : value,
                                },
                            },
                        })
                    }
                />
            </LemonField>
            {alertForm.condition.type !== AlertConditionType.ABSOLUTE_VALUE && (
                <Group name={['threshold', 'configuration']}>
                    <LemonField name="type">
                        <LemonSegmentedButton
                            options={[
                                {
                                    value: InsightThresholdType.PERCENTAGE,
                                    label: '%',
                                    tooltip: 'Percent',
                                },
                                {
                                    value: InsightThresholdType.ABSOLUTE,
                                    label: '#',
                                    tooltip: 'Absolute number',
                                },
                            ]}
                        />
                    </LemonField>
                </Group>
            )}
        </div>
    )
}
