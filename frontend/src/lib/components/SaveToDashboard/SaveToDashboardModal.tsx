import React, { FormEvent } from 'react'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { useActions, useValues } from 'kea'
import { Select, Modal } from 'antd'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { saveToDashboardModalLogic } from 'lib/components/SaveToDashboard/saveToDashboardModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardItemType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

interface SaveToDashboardModalProps {
    visible: boolean
    closeModal: () => void
    insight: Partial<DashboardItemType>
}

export function SaveToDashboardModal({ visible, closeModal, insight }: SaveToDashboardModalProps): JSX.Element {
    const logic = saveToDashboardModalLogic({ id: insight.short_id, fromDashboard: insight.dashboard || undefined })
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { dashboardId } = useValues(logic)
    const { addNewDashboard, setDashboardId } = useActions(logic)
    const { reportSavedInsightToDashboard } = useActions(eventUsageLogic)
    const { insightLoading } = useValues(insightLogic)
    const { updateInsight } = useActions(insightLogic)

    async function save(event: MouseEvent | FormEvent): Promise<void> {
        event.preventDefault()
        updateInsight({ ...insight, dashboard: dashboardId }, () => {
            reportSavedInsightToDashboard()
            toast(
                <div data-attr="success-toast">
                    Panel added to dashboard.&nbsp;
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
            visible={visible}
            title="Add to dashboard"
            okText="Add insight to dashboard"
        >
            <form onSubmit={(e) => void save(e)}>
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
