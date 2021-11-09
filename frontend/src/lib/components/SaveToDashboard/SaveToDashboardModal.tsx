import React, { FormEvent, useState } from 'react'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { useActions, useValues } from 'kea'
import { Input, Select, Modal } from 'antd'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { saveToDashboardModalLogic } from 'lib/components/SaveToDashboard/saveToDashboardModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardItemType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

interface SaveToDashboardModalProps {
    closeModal: () => void
    insight: Partial<DashboardItemType>
}

export function SaveToDashboardModal({ closeModal, insight }: SaveToDashboardModalProps): JSX.Element {
    const logic = saveToDashboardModalLogic({ id: insight.id, fromDashboard: insight.dashboard || undefined })
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { dashboardId } = useValues(logic)
    const { addNewDashboard, setDashboardId } = useActions(logic)
    const { reportSavedInsightToDashboard } = useActions(eventUsageLogic)
    const { insightLoading } = useValues(insightLogic)
    const { updateInsight } = useActions(insightLogic)
    const [name, setName] = useState(insight?.name || '')
    const newItem = !insight.dashboard

    async function save(event: MouseEvent | FormEvent): Promise<void> {
        event.preventDefault()
        updateInsight({ ...insight, name, dashboard: dashboardId }, () => {
            reportSavedInsightToDashboard()
            toast(
                <div data-attr="success-toast">
                    {newItem ? 'Panel added to dashboard.' : 'Panel updated!'}&nbsp;
                    <Link to={`/dashboard/${dashboardId}`}>Click here to see it.</Link>
                </div>
            )
            closeModal()
        })
    }

    return (
        <Modal
            onOk={(e) => void save(e)}
            onCancel={closeModal}
            afterClose={closeModal}
            confirmLoading={insightLoading}
            visible
            title={newItem ? 'Add graph to dashboard' : 'Update graph on dashboard'}
            okText={newItem ? 'Add panel to dashboard' : 'Update panel on dashboard'}
        >
            <form onSubmit={(e) => void save(e)}>
                <label>Panel name on dashboard</label>
                <Input
                    name="name"
                    required
                    type="text"
                    placeholder="Users who did x"
                    autoFocus={!name}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                />

                <br />
                <br />

                <label>Dashboard</label>
                <Select
                    value={dashboardId}
                    onChange={(id) => (id === 'new' ? addNewDashboard() : setDashboardId(id))}
                    style={{ width: '100%' }}
                >
                    {nameSortedDashboards.map((dashboard) => (
                        <Select.Option key={dashboard.id} value={dashboard.id}>
                            {dashboard.name}
                        </Select.Option>
                    ))}
                    <Select.Option value="new">+ New Dashboard</Select.Option>
                </Select>
            </form>
        </Modal>
    )
}
