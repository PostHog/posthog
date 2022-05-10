import React from 'react'
import { Input } from 'antd'
import { useActions, useValues } from 'kea'
import { Field } from 'lib/forms/Field'
import TextArea from 'antd/lib/input/TextArea'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { LemonButton } from 'lib/components/LemonButton'
import { AvailableFeature } from '~/types'
import { LemonSelect } from 'lib/components/LemonSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { DASHBOARD_RESTRICTION_OPTIONS } from './ShareModal'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal } = useActions(newDashboardLogic)
    const { isNewDashboardSubmitting, newDashboardModalVisible } = useValues(newDashboardLogic)

    return (
        <LemonModal
            title="New dashboard"
            destroyOnClose
            onCancel={hideNewDashboardModal}
            visible={newDashboardModalVisible}
            footer={
                <>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-cancel"
                        loading={isNewDashboardSubmitting}
                        style={{ marginRight: '0.5rem' }}
                        onClick={hideNewDashboardModal}
                    >
                        Cancel
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
            <VerticalForm logic={newDashboardLogic} formKey="newDashboard" id="new-dashboard-form" enableFormOnSubmit>
                <p>Use dashboards to compose multiple insights into a single view.</p>
                <Field name="name" label="Name">
                    <Input autoFocus={true} data-attr="dashboard-name-input" className="ph-ignore-input" />
                </Field>
                <Field name="description" label="Description" showOptional>
                    <TextArea data-attr="dashboard-description-input" className="ph-ignore-input" />
                </Field>
                <Field name="useTemplate" label="Template" showOptional>
                    {({ value, onValueChange }) => (
                        <LemonSelect
                            value={value}
                            onChange={onValueChange}
                            placeholder="Optionally start from template"
                            allowClear
                            options={{
                                DEFAULT_APP: {
                                    label: 'Website',
                                    'data-attr': 'dashboard-select-default-app',
                                },
                            }}
                            type="stealth"
                            outlined
                            style={{
                                width: '100%',
                            }}
                            data-attr="copy-from-template"
                        />
                    )}
                </Field>
                <Field name="restrictionLevel" label="Collaboration settings">
                    {({ value, onValueChange }) => (
                        <PayGateMini feature={AvailableFeature.DASHBOARD_PERMISSIONING}>
                            <LemonSelect
                                value={value}
                                onChange={onValueChange}
                                options={DASHBOARD_RESTRICTION_OPTIONS}
                                loading={isNewDashboardSubmitting}
                                type="stealth"
                                outlined
                                style={{
                                    width: '100%',
                                }}
                            />
                        </PayGateMini>
                    )}
                </Field>
            </VerticalForm>
        </LemonModal>
    )
}
