import React, { FormEvent, useState } from 'react'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { useActions, useValues } from 'kea'
import { Input, Select, Modal, Radio } from 'antd'
import dayjs from 'dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { saveToDashboardModalLogic } from 'lib/components/SaveToDashboard/saveToDashboardModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { teamLogic } from '../../../scenes/teamLogic'

const radioStyle: React.CSSProperties = {
    display: 'block',
    overflow: 'hidden',
    whiteSpace: 'normal',
}

interface SaveToDashboardModalProps {
    closeModal: () => void
    name: string
    filters: any
    fromItem: any
    fromDashboard: any
    fromItemName: string
    annotations: any
}

export function SaveToDashboardModal({
    closeModal,
    name: initialName,
    filters,
    fromItem,
    fromDashboard,
    fromItemName,
    annotations,
}: SaveToDashboardModalProps): JSX.Element {
    const logic = saveToDashboardModalLogic({ fromDashboard })
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { currentTeamId } = useValues(teamLogic)
    const { dashboardId } = useValues(logic)
    const { addNewDashboard, setDashboardId } = useActions(logic)
    const { reportSavedInsightToDashboard } = useActions(eventUsageLogic)
    const [name, setName] = useState(fromItemName || initialName || '')
    const [visible, setVisible] = useState(true)
    const [newItem, setNewItem] = useState(!fromItem)
    const fromDashboardName =
        (fromDashboard ? nameSortedDashboards.find((d) => d.id === parseInt(fromDashboard)) : null)?.name || 'Untitled'

    async function save(event: MouseEvent | FormEvent): Promise<void> {
        event.preventDefault()
        if (newItem) {
            const response = await api.create(`api/projects/${currentTeamId}/insights`, {
                filters,
                name,
                saved: true,
                dashboard: dashboardId,
            })
            if (annotations) {
                for (const { content, date_marker, created_at, scope } of annotations) {
                    await api.create(`api/projects/${currentTeamId}/annotations`, {
                        content,
                        date_marker: dayjs(date_marker),
                        created_at,
                        dashboard_item: response.id,
                        scope,
                    })
                }
            }
        } else {
            await api.update(`api/projects/${currentTeamId}/insights/${fromItem}`, { filters })
        }
        reportSavedInsightToDashboard()
        toast(
            <div data-attr="success-toast">
                {newItem ? 'Panel added to dashboard.' : 'Panel updated!'}&nbsp;
                <Link to={`/dashboard/${dashboardId}`}>Click here to see it.</Link>
            </div>
        )
        closeModal()
    }

    return (
        <Modal
            onOk={(e) => void save(e)}
            onCancel={() => setVisible(false)}
            afterClose={closeModal}
            visible={visible}
            title="Add graph to dashboard"
            okText={newItem ? 'Add panel to dashboard' : 'Update panel on dashboard'}
        >
            <form onSubmit={(e) => void save(e)}>
                {fromItem ? (
                    <Radio.Group
                        onChange={(e) => setNewItem(e.target.value === 'true')}
                        value={`${newItem}`}
                        style={{ display: 'block', marginBottom: newItem ? 30 : 0 }}
                    >
                        <Radio style={radioStyle} value={'false'}>
                            Update the existing panel "{fromItemName}" on "{fromDashboardName}"
                        </Radio>
                        <Radio style={radioStyle} value={'true'}>
                            Add as a new panel
                        </Radio>
                    </Radio.Group>
                ) : null}
                {newItem ? (
                    <>
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
                    </>
                ) : null}
            </form>
        </Modal>
    )
}
