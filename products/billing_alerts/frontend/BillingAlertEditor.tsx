import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertAdvancedOptions } from 'products/alerts/frontend/components/AlertAdvancedOptions'
import { AlertDefinitionRow, AlertNextEvaluationStatus } from 'products/alerts/frontend/components/AlertDefinition'
import {
    AlertEditor,
    AlertEditorFormDetails,
    AlertEditorSection,
} from 'products/alerts/frontend/components/AlertEditor'

import { billingAlertFormLogic, BillingAlertFormLogicProps } from './billingAlertFormLogic'
import { BillingAlertHistory } from './BillingAlertHistory'
import { billingAlertNotificationLogic } from './billingAlertNotificationLogic'
import { BillingAlertNotifications } from './BillingAlertNotifications'
import { billingAlertsLogic } from './billingAlertsLogic'

export function BillingAlertEditor(props: BillingAlertFormLogicProps): JSX.Element {
    const notificationProps = { alert: props.alert }

    return (
        <BindLogic logic={billingAlertFormLogic} props={props}>
            <BindLogic logic={billingAlertNotificationLogic} props={notificationProps}>
                <BillingAlertEditorContent {...props} />
            </BindLogic>
        </BindLogic>
    )
}

function BillingAlertEditorContent(props: BillingAlertFormLogicProps): JSX.Element {
    const { alertForm, alertFormChanged, isAlertFormSubmitting } = useValues(billingAlertFormLogic)
    const { setAlertFormValue } = useActions(billingAlertFormLogic)
    const { pendingDestinations } = useValues(billingAlertNotificationLogic)
    const { closeEditor, checkNow } = useActions(billingAlertsLogic)
    const { checkingAlertId } = useValues(billingAlertsLogic)
    const enabledAdvancedOptionsCount =
        Number(alertForm.minimumValue > 0) +
        Number(alertForm.evaluationDelayHours !== 6) +
        Number(alertForm.checkIntervalHours !== 24) +
        Number(alertForm.cooldownHours !== 24)

    return (
        <Form
            logic={billingAlertFormLogic}
            props={props}
            formKey="alertForm"
            enableFormOnSubmit
            data-attr="billing-alert-shared-editor-form"
        >
            <AlertEditor
                title={props.alert ? 'Edit billing alert' : 'New billing alert'}
                description="Billing alerts evaluate organization spend or usage against a daily threshold."
                onBack={closeEditor}
                isEditing={props.alert !== null}
                isSubmitting={isAlertFormSubmitting}
                hasChanges={alertFormChanged}
                hasPendingChanges={pendingDestinations.length > 0}
                leadingActions={
                    props.alert ? (
                        <LemonButton
                            type="secondary"
                            icon={<IconPlay />}
                            onClick={() => checkNow(props.alert!)}
                            loading={checkingAlertId === props.alert.id}
                            data-attr="billing-alert-check-now"
                        >
                            Check now
                        </LemonButton>
                    ) : undefined
                }
                contentClassName="space-y-6"
            >
                <div className="space-y-6 max-w-2xl" data-attr="billing-alert-shared-editor">
                    <AlertEditorFormDetails
                        enabled={{ checked: alertForm.enabled, dataAttr: 'billing-alert-enabled' }}
                        nameDataAttr="billing-alert-name"
                    />
                    <LemonField name="description" label="Description">
                        <LemonTextArea placeholder="What should your team do when this fires?" />
                    </LemonField>

                    <AlertEditorSection
                        title="Definition"
                        description="Billing data uses UTC date boundaries and completed daily values."
                    >
                        <div className="space-y-4" data-attr="billing-alert-definition">
                            <AlertDefinitionRow label="Alert on">
                                <LemonSelect
                                    value={alertForm.metric}
                                    onChange={(metric) => setAlertFormValue('metric', metric)}
                                    options={[
                                        { value: 'spend', label: 'Spend' },
                                        { value: 'usage', label: 'Usage' },
                                    ]}
                                    size="small"
                                    data-attr="billing-alert-metric"
                                />
                                <span className="text-sm">when it</span>
                                <LemonSelect
                                    value={alertForm.thresholdType}
                                    onChange={(thresholdType) => setAlertFormValue('thresholdType', thresholdType)}
                                    options={[
                                        { value: 'relative_increase', label: 'increases by' },
                                        { value: 'absolute_value', label: 'goes above' },
                                        { value: 'absolute_increase', label: 'increases over baseline by' },
                                    ]}
                                    size="small"
                                    data-attr="billing-alert-threshold-type"
                                />
                                {alertForm.thresholdType === 'relative_increase' ? (
                                    <LemonField name="thresholdPercentage">
                                        <LemonInput
                                            type="number"
                                            min={0.01}
                                            step={0.01}
                                            value={alertForm.thresholdPercentage}
                                            onChange={(value) => setAlertFormValue('thresholdPercentage', value ?? 0)}
                                            suffix={<span>%</span>}
                                            className="w-28"
                                            size="small"
                                            data-attr="billing-alert-threshold-percentage"
                                        />
                                    </LemonField>
                                ) : (
                                    <LemonField name="thresholdValue">
                                        <LemonInput
                                            type="number"
                                            min={0}
                                            value={alertForm.thresholdValue}
                                            onChange={(value) => setAlertFormValue('thresholdValue', value ?? 0)}
                                            prefix={alertForm.metric === 'spend' ? <span>$</span> : undefined}
                                            className="w-32"
                                            size="small"
                                            data-attr="billing-alert-threshold-value"
                                        />
                                    </LemonField>
                                )}
                            </AlertDefinitionRow>
                            {alertForm.thresholdType !== 'absolute_value' ? (
                                <AlertDefinitionRow label="Compare against the previous">
                                    <LemonField name="baselineWindowDays">
                                        <LemonInput
                                            type="number"
                                            min={1}
                                            max={90}
                                            value={alertForm.baselineWindowDays}
                                            onChange={(value) => setAlertFormValue('baselineWindowDays', value ?? 1)}
                                            suffix={<span>days</span>}
                                            className="w-28"
                                            size="small"
                                        />
                                    </LemonField>
                                </AlertDefinitionRow>
                            ) : null}
                            <AlertNextEvaluationStatus loading={false}>
                                {props.alert?.next_check_at
                                    ? dayjs(props.alert.next_check_at).format('MMM D, HH:mm [UTC]')
                                    : 'after the alert is created'}
                            </AlertNextEvaluationStatus>
                        </div>
                    </AlertEditorSection>

                    <AlertEditorSection title="Notifications">
                        <BillingAlertNotifications alert={props.alert} />
                    </AlertEditorSection>

                    <AlertAdvancedOptions enabledCount={enabledAdvancedOptionsCount}>
                        <div
                            className="grid grid-cols-1 md:grid-cols-2 gap-3"
                            data-attr="billing-alert-advanced-options"
                        >
                            <LemonField name="minimumValue" label="Minimum current value">
                                <LemonInput
                                    type="number"
                                    min={0}
                                    value={alertForm.minimumValue}
                                    onChange={(value) => setAlertFormValue('minimumValue', value ?? 0)}
                                    prefix={alertForm.metric === 'spend' ? <span>$</span> : undefined}
                                />
                            </LemonField>
                            <LemonField name="evaluationDelayHours" label="Evaluation delay">
                                <LemonInput
                                    type="number"
                                    min={0}
                                    max={72}
                                    value={alertForm.evaluationDelayHours}
                                    onChange={(value) => setAlertFormValue('evaluationDelayHours', value ?? 0)}
                                    suffix={<span>hours</span>}
                                />
                            </LemonField>
                            <LemonField name="checkIntervalHours" label="Check interval">
                                <LemonInput
                                    type="number"
                                    min={1}
                                    max={24}
                                    value={alertForm.checkIntervalHours}
                                    onChange={(value) => setAlertFormValue('checkIntervalHours', value ?? 1)}
                                    suffix={<span>hours</span>}
                                />
                            </LemonField>
                            <LemonField name="cooldownHours" label="Notification cooldown">
                                <LemonInput
                                    type="number"
                                    min={0}
                                    max={720}
                                    value={alertForm.cooldownHours}
                                    onChange={(value) => setAlertFormValue('cooldownHours', value ?? 0)}
                                    suffix={<span>hours</span>}
                                />
                            </LemonField>
                        </div>
                    </AlertAdvancedOptions>

                    {props.alert ? <BillingAlertHistory alert={props.alert} /> : null}
                </div>
            </AlertEditor>
        </Form>
    )
}
