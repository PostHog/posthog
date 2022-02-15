import React from 'react'
import { Input, Form, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { slugify } from 'lib/utils'
import { dashboardsModel } from '~/models/dashboardsModel'
import TextArea from 'antd/lib/input/TextArea'
import { LemonModal } from 'lib/components/LemonModal/LemonModal'
import { dashboardsLogic } from './dashboardsLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { DashboardRestrictionLevel, FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature } from '~/types'
import { LemonSelect, LemonSelectOptions } from 'lib/components/LemonSelect'
import { DASHBOARD_RESTRICTION_OPTIONS } from './ShareModal'

export function NewDashboardModal(): JSX.Element {
    const { hideNewDashboardModal } = useActions(dashboardsLogic)
    const { newDashboardModalVisible } = useValues(dashboardsLogic)
    const { addDashboard } = useActions(dashboardsModel)
    const { dashboardLoading } = useValues(dashboardsModel)
    const { featureFlags } = useValues(featureFlagLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const permissioningAvailable = hasAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING)

    const restrictionOptions: LemonSelectOptions = Object.fromEntries(
        Object.entries(DASHBOARD_RESTRICTION_OPTIONS).map(([key, option]) => [
            key,
            {
                ...option,
                disabled: !permissioningAvailable,
            },
        ])
    )

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
                    <Select
                        data-attr="copy-from-template"
                        style={{ width: '100%' }}
                        placeholder="Optionally start from template"
                    >
                        <Select.Option data-attr="dashboard-select-empty" value="">
                            Empty Dashboard
                        </Select.Option>
                        <Select.Option data-attr="dashboard-select-default-app" value="DEFAULT_APP">
                            Default Dashboard - Web App
                        </Select.Option>
                    </Select>
                </Form.Item>
                {featureFlags[FEATURE_FLAGS.DASHBOARD_PERMISSIONS] && (
                    <Form.Item
                        name="restrictionLevel"
                        label="Collaboration"
                        rules={[{ required: true, message: 'Restriction level needs to be specified.' }]}
                    >
                        <LemonSelect
                            value={form.getFieldValue('restrictionLevel')}
                            onChange={(newValue) =>
                                form.setFieldsValue({
                                    restrictionLevel: newValue,
                                })
                            }
                            options={restrictionOptions}
                            loading={dashboardLoading}
                            type="stealth"
                            outlined
                            style={{
                                height: '3rem',
                                width: '100%',
                            }}
                        />
                    </Form.Item>
                )}
            </Form>
        </LemonModal>
    )
}
