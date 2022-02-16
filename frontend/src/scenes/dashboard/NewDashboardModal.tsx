import React from 'react'
import { Input, Form } from 'antd'
import { useActions, useValues } from 'kea'
import { slugify } from 'lib/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import TextArea from 'antd/lib/input/TextArea'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { dashboardsLogic } from './dashboardsLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { DashboardRestrictionLevel, FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { AvailableFeature } from '~/types'
import { LemonSelect } from 'lib/components/LemonSelect'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { DASHBOARD_RESTRICTION_OPTIONS } from './ShareModal'

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal } = useActions(dashboardsLogic)
    const { newDashboardModalVisible } = useValues(dashboardsLogic)
    const { addDashboard } = useActions(dashboardsModel)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { featureFlags } = useValues(featureFlagLogic)

    const [form] = Form.useForm()

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
                        loading={dashboardLoading}
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
                        loading={dashboardLoading}
                    >
                        Create
                    </LemonButton>
                </>
            }
        >
            <Form
                layout="vertical"
                form={form}
                onFinish={(values) => {
                    addDashboard(values)
                }}
                id="new-dashboard-form"
                requiredMark="optional"
                initialValues={{
                    restrictionLevel: DashboardRestrictionLevel.EveryoneInProjectCanEdit,
                }}
            >
                <p>Use dashboards to compose multiple insights into a single view.</p>
                <Form.Item
                    name="name"
                    label="Name"
                    rules={[{ required: true, message: 'Please give your dashboard a name.' }]}
                >
                    <Input
                        autoFocus={true}
                        onChange={(e) => form.setFieldsValue({ key: slugify(e.target.value) })}
                        data-attr="dashboard-name-input"
                        className="ph-ignore-input"
                    />
                </Form.Item>
                <Form.Item name="description" label="Description">
                    <TextArea
                        onChange={(e) => form.setFieldsValue({ description: e.target.value })}
                        data-attr="dashboard-description-input"
                        className="ph-ignore-input"
                    />
                </Form.Item>
                <Form.Item name="useTemplate" label="Template">
                    <LemonSelect
                        value={form.getFieldValue('useTemplate')}
                        onChange={(newValue) =>
                            form.setFieldsValue({
                                useTemplate: newValue,
                            })
                        }
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
                </Form.Item>
                {featureFlags[FEATURE_FLAGS.DASHBOARD_PERMISSIONS] && (
                    <Form.Item
                        name="restrictionLevel"
                        label="Collaboration settings"
                        rules={[{ required: true, message: 'Restriction level needs to be specified.' }]}
                    >
                        <PayGateMini feature={AvailableFeature.DASHBOARD_PERMISSIONING}>
                            <LemonSelect
                                value={form.getFieldValue('restrictionLevel')}
                                onChange={(newValue) =>
                                    form.setFieldsValue({
                                        restrictionLevel: newValue,
                                    })
                                }
                                options={DASHBOARD_RESTRICTION_OPTIONS}
                                loading={dashboardLoading}
                                type="stealth"
                                outlined
                                style={{
                                    width: '100%',
                                }}
                            />
                        </PayGateMini>
                    </Form.Item>
                )}
            </Form>
        </LemonModal>
    )
}
