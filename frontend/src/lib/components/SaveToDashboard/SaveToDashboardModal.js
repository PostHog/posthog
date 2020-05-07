import React, { useState } from 'react'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { Modal } from 'lib/components/Modal'
import { useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { Input, Select } from 'antd'

export function SaveToDashboardModal({ closeModal, name: initialName, type, filters }) {
    const { dashboards } = useValues(dashboardsModel)
    const [dashboardId, setDashboardId] = useState(dashboards.length > 0 ? dashboards[0].id : null)
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
                <label>Dashboard</label>
                <Select value={dashboardId} onChange={setDashboardId} style={{ width: '100%' }}>
                    {dashboards.map(dashboard => (
                        <Select.Option key={dashboard.id} value={dashboard.id}>
                            {dashboard.name}
                        </Select.Option>
                    ))}
                </Select>
                <br />
                <br />
                <label>Panel name on dashboard</label>
                <Input
                    name="name"
                    required
                    type="text"
                    className="form-control"
                    placeholder="Users who did x"
                    value={name}
                    onChange={e => setName(e.target.value)}
                />
            </form>
        </Modal>
    )
}
