import { Form, Modal, Input, Switch, Select } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { prompt } from 'lib/logic/prompt'
import { router } from 'kea-router'
import React, { useState } from 'react'
import { dashboardsModel } from '~/models'
import { AnnotationType, DashboardType } from '~/types'
import { saveInsightModalLogicType } from './SaveInsightModalType'

interface SaveInsightModalProps {
    shortId: string
    onClose: () => void
    annotations: AnnotationType[]
}

const saveInsightModalLogic = kea<saveInsightModalLogicType<DashboardType>>({
    connect: {
        values: [dashboardsModel, ['dashboards', 'lastDashboardId']],
    },
    actions: () => ({
        addNewDashboard: true,
        setDashboardId: (id: number) => ({ id }),
    }),
    reducers: {
        _dashboardId: [null as null | number, { setDashboardId: (_, { id }) => id }],
    },
    selectors: ({ props }) => ({
        dashboards: [
            () => [dashboardsModel.selectors.dashboards],
            (dashboards: DashboardType[]): DashboardType[] => dashboards,
        ],
        dashboardId: [
            (s) => [s._dashboardId, s.dashboards, dashboardsModel.selectors.lastDashboardId],
            (_dashboardId, dashboards, lastDashboardId): number | null =>
                _dashboardId ||
                props.fromDashboard ||
                lastDashboardId ||
                (dashboards.length > 0 ? dashboards[0].id : null),
        ],
    }),

    listeners: ({ actions }) => ({
        setDashboardId: ({ id }) => {
            dashboardsModel.actions.setLastDashboardId(id)
        },
        /*addNewDashboard: async () => {
            prompt({ key: `saveToDashboardModalLogic-new-dashboard` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name) => dashboardsModel.actions.addDashboard({ name }),
            })
        },*/
        [dashboardsModel.actions.addDashboardSuccess]: async ({ dashboard }) => {
            //eventUsageLogic.actions.reportCreatedDashboardFromModal()
            actions.setDashboardId(dashboard.id)
        },
    }),
})

export function SaveInsightModal({ shortId, onClose, annotations }: SaveInsightModalProps): JSX.Element {
    const [closing, setClosing] = useState(false)
    const [{ fromItem, fromItemName, fromDashboard }] = useState(router.values.hashParams)
    const logic = saveInsightModalLogic({ fromDashboard })
    const { dashboards, dashboardId } = useValues(logic)
    const { addNewDashboard } = useActions(logic)
    const [form] = Form.useForm()

    return (
        <>
            <Modal
                visible={!closing}
                title="Save Insight"
                okText="Save"
                onCancel={() => {
                    setClosing(true) // This extra step is done so the closing animation is shown
                    setTimeout(() => onClose(), 500)
                }}
                onOk={() => form.submit()}
            >
                <Form
                    layout="vertical"
                    onFinish={(val) => console.log(val)}
                    requiredMark={false}
                    form={form}
                    initialValues={{ name: fromItemName, dashboard: dashboardId, saveToDashboard: false }}
                >
                    <Form.Item
                        name="name"
                        label="Name"
                        rules={[
                            {
                                required: true,
                                message: 'Please type a name to continue',
                            },
                        ]}
                    >
                        <Input
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="save-insight-name"
                            placeholder="Use a name that is easy to identify"
                            type="text"
                        />
                    </Form.Item>
                    <Form.Item name="description" label="Description">
                        <Input.TextArea
                            className="ph-ignore-input"
                            data-attr="save-insight-description"
                            placeholder="Optional. Help others in your team know what this insight is."
                        />
                    </Form.Item>
                    <Form.Item
                        name="saveToDashboard"
                        label="Save to dashboard"
                        valuePropName="checked"
                        style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 4 }}
                    >
                        <Switch style={{ float: 'right' }} />
                    </Form.Item>
                    <Form.Item
                        shouldUpdate={(prevValues, currentValues) =>
                            prevValues.saveToDashboard !== currentValues.saveToDashboard
                        }
                        style={{ marginBottom: 0 }}
                    >
                        {({ getFieldValue }) => {
                            return (
                                getFieldValue('saveToDashboard') && (
                                    <Form.Item name="dashboard">
                                        <Select
                                            onChange={(val: 'new' | number) => val === 'new' && addNewDashboard()}
                                            style={{ width: '100%' }}
                                        >
                                            {dashboards.map((dashboard) => (
                                                <Select.Option key={dashboard.id} value={dashboard.id}>
                                                    {dashboard.name}
                                                </Select.Option>
                                            ))}
                                            <Select.Option value="new">+ New Dashboard</Select.Option>
                                        </Select>
                                    </Form.Item>
                                )
                            )
                        }}
                    </Form.Item>
                </Form>
            </Modal>
        </>
    )
}
