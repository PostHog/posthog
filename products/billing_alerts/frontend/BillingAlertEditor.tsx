import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconPlay } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { NextScheduledRun } from 'lib/components/ScheduledRunStatus'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AlertDefinitionRow } from 'products/alerts/frontend/components/AlertDefinition'
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
    const isPaused = props.alert !== null && !props.alert.enabled

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
                description="Billing alerts check your organization's billing-period spend once a day against a configured threshold."
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
                            tooltip={
                                isPaused
                                    ? 'This alert is paused, so the check runs as a preview and does not send notifications.'
                                    : undefined
                            }
                            disabledReason={
                                alertFormChanged || pendingDestinations.length > 0
                                    ? 'Save your changes before checking.'
                                    : isAlertFormSubmitting
                                      ? 'Wait for the alert to finish saving.'
                                      : undefined
                            }
                            data-attr="billing-alert-check-now"
                        >
                            {isPaused ? 'Preview check' : 'Check now'}
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
                    <LemonField name="description" label="Internal note">
                        <LemonTextArea placeholder="Only visible in PostHog." />
                    </LemonField>

                    <AlertEditorSection
                        title="Definition"
                        description="You can choose when the daily check runs, but the underlying billing data updates once a day and usually settles around 8-10am UTC."
                    >
                        <div className="space-y-4" data-attr="billing-alert-definition">
                            <AlertDefinitionRow label="Alert on">
                                <LemonSelect
                                    value={alertForm.metric}
                                    onChange={(metric) => setAlertFormValue('metric', metric)}
                                    options={[
                                        { value: 'spend', label: 'Current period spend' },
                                        { value: 'projected_spend', label: 'Projected period spend' },
                                    ]}
                                    size="small"
                                    data-attr="billing-alert-metric"
                                />
                                <span className="text-sm">when it goes above</span>
                                <LemonField name="thresholdValue">
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        value={alertForm.thresholdValue ?? undefined}
                                        onChange={(value) => setAlertFormValue('thresholdValue', value ?? null)}
                                        prefix={<span>$</span>}
                                        className="w-32"
                                        size="small"
                                        data-attr="billing-alert-threshold-value"
                                    />
                                </LemonField>
                            </AlertDefinitionRow>
                            <div className="text-xs text-secondary">
                                {alertForm.metric === 'projected_spend'
                                    ? 'Projected period spend estimates what this billing period will cost by its end, after discounts.'
                                    : 'Current period spend is what this billing period has cost so far, after discounts.'}
                            </div>
                            <NextScheduledRun label="Next planned evaluation:" loading={false}>
                                {props.alert?.next_check_at
                                    ? dayjs.utc(props.alert.next_check_at).format('MMM D, HH:mm [UTC]')
                                    : 'after the alert is created'}
                            </NextScheduledRun>
                        </div>
                    </AlertEditorSection>

                    <AlertEditorSection title="Notifications">
                        <BillingAlertNotifications alert={props.alert} />
                    </AlertEditorSection>

                    {props.alert ? <BillingAlertHistory alert={props.alert} /> : null}
                </div>
            </AlertEditor>
        </Form>
    )
}
