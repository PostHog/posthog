import React, { useState } from 'react'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { kea, useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Input, Select, Modal, Radio } from 'antd'
import { prompt } from 'lib/logic/prompt'
import moment from 'moment'

const saveToDashboardModalLogic = kea({
    actions: () => ({
        addNewDashboard: true,
    }),

    listeners: ({ props }) => ({
        addNewDashboard: async () => {
            prompt({ key: `saveToDashboardModalLogic-new-dashboard` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name) => dashboardsModel.actions.addDashboard({ name }),
            })
        },

        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            props.setDashboardId && props.setDashboardId(dashboard.id)
        },
    }),
})
const radioStyle = {
    display: 'block',
    height: '30px',
    lineHeight: '30px',
}
export function SaveToDashboardModal({
    closeModal,
    name: initialName,
    type,
    filters,
    fromItem,
    fromDashboard,
    fromItemName,
    annotations,
}) {
    const { dashboards, lastVisitedDashboardId } = useValues(dashboardsModel)
    const [dashboardId, setDashboardId] = useState(
        fromDashboard || lastVisitedDashboardId || (dashboards.length > 0 ? dashboards[0].id : null)
    )
    const { addNewDashboard } = useActions(saveToDashboardModalLogic({ setDashboardId }))
    const [name, setName] = useState(fromItemName || initialName || '')
    const [visible, setVisible] = useState(true)
    const [newItem, setNewItem] = useState(!fromItem)
    const fromDashboardName =
        (fromDashboard ? dashboards.find((d) => d.id === parseInt(fromDashboard)) : null)?.name || 'Untitled'

    async function save(event) {
        event.preventDefault()
        if (newItem) {
            const response = await api.create('api/dashboard_item', {
                filters,
                type,
                name,
                dashboard: dashboardId,
            })
            if (annotations) {
                for (const { content, date_marker, created_at, scope } of annotations) {
                    await api.create('api/annotation', {
                        content,
                        date_marker: moment(date_marker),
                        created_at,
                        dashboard_item: response.id,
                        scope,
                    })
                }
            }
        } else {
            await api.update(`api/dashboard_item/${fromItem}`, { filters, type })
        }
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
            onOk={save}
            onCancel={() => setVisible(false)}
            afterClose={closeModal}
            visible={visible}
            title="Add graph to dashboard"
            okText={newItem ? 'Add panel to dashboard' : 'Update panel on dashboard'}
        >
            <form onSubmit={save}>
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
                            className="form-control"
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
                            {dashboards.map((dashboard) => (
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
