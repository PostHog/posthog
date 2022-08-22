import React from 'react'
import { useActions, useValues } from 'kea'
import { Field } from 'lib/forms/Field'
import { LemonButton } from 'lib/components/LemonButton'
import { AvailableFeature } from '~/types'
import { LemonSelect } from 'lib/components/LemonSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { DASHBOARD_RESTRICTION_OPTIONS } from './DashboardCollaborators'
import { LemonModal } from 'lib/components/LemonModal'
import { Form } from 'kea-forms'

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal, createAndGoToDashboard } = useActions(newDashboardLogic)
    const { isNewDashboardSubmitting, newDashboardModalVisible } = useValues(newDashboardLogic)

    return (
        <LemonModal
            title="New dashboard"
            description="Use dashboards to compose multiple insights into a single view."
            onClose={hideNewDashboardModal}
            isOpen={newDashboardModalVisible}
            footer={
                <>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-cancel"
                        loading={isNewDashboardSubmitting}
                        onClick={hideNewDashboardModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-submit-and-go"
                        loading={isNewDashboardSubmitting}
                        disabled={isNewDashboardSubmitting}
                        onClick={createAndGoToDashboard}
                    >
                        Create and go to dashboard
                    </LemonButton>
                    <LemonButton
                        form="new-dashboard-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="dashboard-submit"
                        loading={isNewDashboardSubmitting}
                        disabled={isNewDashboardSubmitting}
                    >
                        Create
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={newDashboardLogic}
                formKey="newDashboard"
                id="new-dashboard-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <p>Use dashboards to compose multiple insights into a single view.</p>
                <Field name="name" label="Name">
                    <LemonInput autoFocus={true} data-attr="dashboard-name-input" className="ph-ignore-input" />
                </Field>
                <Field name="description" label="Description" showOptional>
                    <LemonTextArea data-attr="dashboard-description-input" className="ph-ignore-input" />
                </Field>
                <Field name="useTemplate" label="Template" showOptional>
                    <LemonSelect
                        placeholder="Optionally start from template"
                        allowClear
                        options={[
                            {
                                value: 'DEFAULT_APP',
                                label: 'Website',
                                'data-attr': 'dashboard-select-default-app',
                            },
                        ]}
                        fullWidth
                        data-attr="copy-from-template"
                    />
                </Field>
                <Field name="restrictionLevel" label="Collaboration settings">
                    {({ value, onChange }) => (
                        <PayGateMini feature={AvailableFeature.DASHBOARD_PERMISSIONING}>
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={DASHBOARD_RESTRICTION_OPTIONS}
                                loading={isNewDashboardSubmitting}
                                fullWidth
                            />
                        </PayGateMini>
                    )}
                </Field>
            </Form>
        </LemonModal>
    )
}
