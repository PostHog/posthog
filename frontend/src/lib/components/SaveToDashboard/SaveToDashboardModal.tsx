import React, { FormEvent } from 'react'
import { useActions, useValues } from 'kea'
import { Select, Modal } from 'antd'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { saveToDashboardModalLogic } from 'lib/components/SaveToDashboard/saveToDashboardModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightModel } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { lemonToast } from '../lemonToast'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

interface SaveToDashboardModalProps {
    visible: boolean
    closeModal: () => void
    insight: Partial<InsightModel>
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
            lemonToast.success('Insight added to dashboard', {
                button: {
                    label: 'View dashboard',
                    action: () => router.actions.push(urls.dashboard(dashboardId)),
                },
            })
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
