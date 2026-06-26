import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { AlertingChoiceCard, AlertingWizardLayout } from 'lib/components/Alerting'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { MetricEnumApi, ThresholdTypeEnumApi } from '~/generated/core/api.schemas'

import { BillingAlertDestinationFields } from './BillingAlertDestination'
import {
    BILLING_ALERT_DESTINATIONS,
    BILLING_ALERT_NUMBER_FIELDS,
    BILLING_ALERT_WIZARD_STEPS,
} from './billingAlertDisplay'
import { BILLING_ALERT_TRIGGERS, BillingAlertWizardStep, billingAlertsLogic } from './billingAlertsLogic'
import type { BillingAlertForm } from './billingAlertsLogic'

export function BillingAlertWizard(): JSX.Element {
    const { wizardStep } = useValues(billingAlertsLogic)
    const { setWizardStep, resetCreation } = useActions(billingAlertsLogic)

    return (
        <AlertingWizardLayout
            steps={BILLING_ALERT_WIZARD_STEPS}
            currentStep={wizardStep}
            onStepClick={setWizardStep}
            onCancel={resetCreation}
        >
            {wizardStep === BillingAlertWizardStep.Destination && <BillingAlertDestinationStep />}
            {wizardStep === BillingAlertWizardStep.Trigger && <BillingAlertTriggerStep />}
            {wizardStep === BillingAlertWizardStep.Configure && <BillingAlertConfigureStep />}
        </AlertingWizardLayout>
    )
}

function BillingAlertDestinationStep(): JSX.Element {
    const { selectedDestinationKey } = useValues(billingAlertsLogic)
    const { selectDestination } = useActions(billingAlertsLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Where should PostHog send it?</h2>
                <p className="text-secondary text-sm">Choose the first notification destination for this alert.</p>
            </div>
            <div className="space-y-3">
                {BILLING_ALERT_DESTINATIONS.map((destination) => (
                    <AlertingChoiceCard
                        key={destination.key}
                        icon={<img src={destination.icon} alt="" className="h-8 w-8 object-contain" />}
                        name={destination.name}
                        description={destination.description}
                        selected={selectedDestinationKey === destination.key}
                        onClick={() => selectDestination(destination.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function BillingAlertTriggerStep(): JSX.Element {
    const { selectedTriggerKey } = useValues(billingAlertsLogic)
    const { selectTrigger } = useActions(billingAlertsLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">What should trigger the alert?</h2>
                <p className="text-secondary text-sm">Choose the billing condition to monitor.</p>
            </div>
            <div className="space-y-3">
                {BILLING_ALERT_TRIGGERS.map((trigger) => (
                    <AlertingChoiceCard
                        key={trigger.key}
                        name={trigger.name}
                        description={trigger.description}
                        selected={selectedTriggerKey === trigger.key}
                        onClick={() => selectTrigger(trigger.key)}
                    />
                ))}
            </div>
        </div>
    )
}

function BillingAlertConfigureStep(): JSX.Element {
    const { canSubmit, saving } = useValues(billingAlertsLogic)
    const { createAlert } = useActions(billingAlertsLogic)

    return (
        <div className="space-y-4">
            <div>
                <h2 className="text-xl font-semibold mb-1">Configure your alert</h2>
                <p className="text-secondary text-sm">Set the threshold and notification details.</p>
            </div>
            <div className="deprecated-space-y-4">
                <BillingAlertThresholdFields />
                <BillingAlertDestinationFields />
            </div>
            <div className="flex justify-end gap-2">
                <LemonButton
                    type="primary"
                    onClick={createAlert}
                    loading={saving}
                    disabledReason={!canSubmit ? 'Name, threshold, and destination details are required.' : undefined}
                    data-attr="create-billing-alert"
                >
                    Create alert
                </LemonButton>
            </div>
        </div>
    )
}

function BillingAlertThresholdFields(): JSX.Element {
    const { form } = useValues(billingAlertsLogic)
    const { setFormValue } = useActions(billingAlertsLogic)

    return (
        <>
            <LemonField.Pure label="Name">
                <LemonInput
                    value={form.name}
                    onChange={(name) => setFormValue('name', name)}
                    placeholder="Alert name"
                    data-attr="billing-alert-name"
                />
            </LemonField.Pure>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <LemonField.Pure label="Metric">
                    <LemonSelect
                        value={form.metric}
                        onChange={(metric) => setFormValue('metric', metric as MetricEnumApi)}
                        options={[
                            { value: 'spend', label: 'Spend' },
                            { value: 'usage', label: 'Usage' },
                        ]}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Threshold type">
                    <LemonSelect
                        value={form.threshold_type}
                        onChange={(thresholdType) =>
                            setFormValue('threshold_type', thresholdType as ThresholdTypeEnumApi)
                        }
                        options={[
                            { value: 'relative_increase', label: 'Relative increase' },
                            { value: 'absolute_value', label: 'Absolute value' },
                            { value: 'absolute_increase', label: 'Absolute increase' },
                        ]}
                    />
                </LemonField.Pure>
                {form.threshold_type === 'relative_increase' ? (
                    <LemonField.Pure label="Increase">
                        <LemonInput
                            type="number"
                            value={form.threshold_percentage}
                            onChange={(thresholdPercentage) =>
                                setFormValue('threshold_percentage', thresholdPercentage ?? 0)
                            }
                            suffix={<span>%</span>}
                            min={0}
                            data-attr="billing-alert-threshold-percentage"
                        />
                    </LemonField.Pure>
                ) : (
                    <LemonField.Pure label={form.metric === 'spend' ? 'Amount' : 'Value'}>
                        <LemonInput
                            type="number"
                            value={form.threshold_value}
                            onChange={(thresholdValue) => setFormValue('threshold_value', thresholdValue ?? undefined)}
                            prefix={form.metric === 'spend' ? <span>$</span> : undefined}
                            min={0}
                            data-attr="billing-alert-threshold-value"
                        />
                    </LemonField.Pure>
                )}
                {BILLING_ALERT_NUMBER_FIELDS.map((field) => (
                    <BillingAlertNumberField key={field.key} field={field} form={form} setFormValue={setFormValue} />
                ))}
            </div>
        </>
    )
}

function BillingAlertNumberField({
    field,
    form,
    setFormValue,
}: {
    field: (typeof BILLING_ALERT_NUMBER_FIELDS)[number]
    form: BillingAlertForm
    setFormValue: (key: keyof BillingAlertForm, value: BillingAlertForm[keyof BillingAlertForm]) => void
}): JSX.Element {
    return (
        <LemonField.Pure label={field.label}>
            <LemonInput
                type="number"
                value={form[field.key]}
                onChange={(value) => setFormValue(field.key, value ?? field.min)}
                prefix={field.prefixSpend && form.metric === 'spend' ? <span>$</span> : undefined}
                suffix={field.suffix ? <span>{field.suffix}</span> : undefined}
                min={field.min}
                max={field.max}
            />
        </LemonField.Pure>
    )
}
