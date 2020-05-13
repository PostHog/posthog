import React, { useState } from 'react'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { Modal } from 'lib/components/Modal'
import { kea, useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Input, Select } from 'antd'
import { prompt } from 'lib/logic/prompt'

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
                success: name => dashboardsModel.actions.addDashboard({ name }),
            })
        },

        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            props.setDashboardId && props.setDashboardId(dashboard.id)
        },
    }),
})

export function SaveToDashboardModal({ closeModal, name: initialName, type, filters }) {
    const { dashboards, lastVisitedDashboardId } = useValues(dashboardsModel)
    const [dashboardId, setDashboardId] = useState(
        lastVisitedDashboardId || (dashboards.length > 0 ? dashboards[0].id : null)
    )
    const { addNewDashboard } = useActions(saveToDashboardModalLogic({ setDashboardId }))
    const [name, setName] = useState(initialName || '')

    function save(event) {
        event.preventDefault()
        api.create('api/dashboard_item', { filters, type, name, dashboard: dashboardId }).then(() => {
            toast(
                <div>
                    Panel added to dashboard.&nbsp;
                    <Link to={`/dashboard/${dashboardId}`}>Click here to see it.</Link>
                </div>
            )
            closeModal()
        })
    }

    return (
        <Modal
            title="Add graph to dashboard"
            onDismiss={closeModal}
            footer={
                <button type="submit" className="btn btn-success" onClick={save}>
                    Add panel to dashboard
                </button>
            }
        >
            <form onSubmit={save}>
                <label>Panel name on dashboard</label>
                <Input
                    name="name"
                    required
                    type="text"
                    className="form-control"
                    placeholder="Users who did x"
                    autoFocus={!name}
                    value={name}
                    onChange={e => setName(e.target.value)}
                />

                <br />
                <br />

                <label>Dashboard</label>
                <Select
                    value={dashboardId}
                    onChange={id => (id === 'new' ? addNewDashboard() : setDashboardId(id))}
                    style={{ width: '100%' }}
                >
                    {dashboards.map(dashboard => (
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
