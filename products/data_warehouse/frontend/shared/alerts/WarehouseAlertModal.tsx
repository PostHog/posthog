import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSegmentedButton,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    PlatformAlertConfigurationSourceKindEnumApi,
    WarehouseAlertGroupByEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { warehouseAlertModalLogic } from './warehouseAlertModalLogic'
import { WarehouseAlertNotifications } from './WarehouseAlertNotifications'
import { WarehouseAlertsLogicProps, warehouseAlertsLogic } from './warehouseAlertsLogic'

export function WarehouseAlertModal(props: WarehouseAlertsLogicProps): JSX.Element {
    const logic = warehouseAlertModalLogic(props)
    const { isOpen, editing, isAlertFormSubmitting } = useValues(logic)
    const { closeModal, submitAlertForm } = useActions(logic)
    const { targetOptions } = useValues(warehouseAlertsLogic(props))
    const { deleteAlert } = useActions(warehouseAlertsLogic(props))

    const isSourceAlert = props.kind === PlatformAlertConfigurationSourceKindEnumApi.WarehouseSource
    const noun = isSourceAlert ? 'source' : 'destination'

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            // Closing mid-save would unmount the notifications editor and drop the destinations a new alert still has to add.
            closable={!isAlertFormSubmitting}
            title={editing ? 'Edit alert' : 'New alert'}
            description={
                isSourceAlert
                    ? 'Get notified when a source fails to sync, and again when it recovers.'
                    : 'Get notified when a destination fails to receive synced rows, and again when it recovers.'
            }
            width={640}
            footer={
                <>
                    {editing ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            className="mr-auto"
                            disabledReason={isAlertFormSubmitting ? 'Saving the alert' : undefined}
                            onClick={() => {
                                closeModal()
                                deleteAlert(editing)
                            }}
                            data-attr="warehouse-alert-modal-delete"
                        >
                            Delete
                        </LemonButton>
                    ) : null}
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={isAlertFormSubmitting ? 'Saving the alert' : undefined}
                        data-attr="warehouse-alert-modal-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitAlertForm}
                        loading={isAlertFormSubmitting}
                        data-attr="warehouse-alert-modal-save"
                    >
                        {editing ? 'Save' : 'Create alert'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={warehouseAlertModalLogic} props={props} formKey="alertForm" className="flex flex-col gap-4">
                <LemonField name="name" label="Name">
                    <LemonInput data-attr="warehouse-alert-name" />
                </LemonField>

                <LemonField
                    name="targetIds"
                    label={isSourceAlert ? 'Sources' : 'Destinations'}
                    help={`Leave empty to watch every ${noun}, including ones you add later.`}
                >
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="multiple"
                            value={value}
                            onChange={onChange}
                            placeholder={`All ${noun}s`}
                            options={targetOptions.map((option) => ({ key: option.id, label: option.label }))}
                            data-attr="warehouse-alert-targets"
                        />
                    )}
                </LemonField>

                {isSourceAlert ? (
                    <>
                        <LemonField
                            name="groupBy"
                            label="Send one alert"
                            help={
                                editing
                                    ? 'Changing this closes the alerts that are firing now. They fire again on the next check if the failure continues.'
                                    : undefined
                            }
                        >
                            {({ value, onChange }) => (
                                <LemonSegmentedButton
                                    value={value}
                                    onChange={onChange}
                                    options={[
                                        { value: WarehouseAlertGroupByEnumApi.Source, label: 'Per source' },
                                        { value: WarehouseAlertGroupByEnumApi.Schema, label: 'Per table' },
                                    ]}
                                    size="small"
                                    data-attr="warehouse-alert-group-by"
                                />
                            )}
                        </LemonField>
                        <LemonField name="includeBillingLimits">
                            {({ value, onChange }) => (
                                <LemonCheckbox
                                    checked={value}
                                    onChange={onChange}
                                    label="Also alert when a table stops syncing at the billing limit"
                                    data-attr="warehouse-alert-billing-limits"
                                />
                            )}
                        </LemonField>
                    </>
                ) : null}

                <LemonField name="emailProjectMembers">
                    {({ value, onChange }) => (
                        <LemonCheckbox
                            checked={value}
                            onChange={onChange}
                            label="Email the project members who get data pipeline error emails"
                            data-attr="warehouse-alert-email-members"
                        />
                    )}
                </LemonField>

                {editing ? (
                    <LemonField name="enabled">
                        {({ value, onChange }) => (
                            <LemonSwitch
                                checked={value}
                                onChange={onChange}
                                label="Alert is on"
                                bordered
                                data-attr="warehouse-alert-enabled"
                            />
                        )}
                    </LemonField>
                ) : null}
            </Form>

            <LemonDivider className="my-4" />
            <h4 className="mb-2">Other notification destinations</h4>
            {/* Mounted only while open, so a closed modal drops destinations a new alert never saved. */}
            {isOpen ? <WarehouseAlertNotifications alertId={editing?.id} /> : null}
        </LemonModal>
    )
}
