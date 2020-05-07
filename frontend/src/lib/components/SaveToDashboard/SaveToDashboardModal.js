import React, { useState } from 'react'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { Link } from 'lib/components/Link'
import { Modal } from 'lib/components/Modal'

export function SaveToDashboardModal({ closeModal, name: initialName, type, filters }) {
    const [name, setName] = useState(initialName)

    function save(event) {
        event.preventDefault()
        api.create('api/dashboard', { filters, type, name }).then(() => {
            toast(
                <div>
                    Panel added to dashboard.&nbsp;
                    <Link to="/dashboard">Click here to see it.</Link>
                </div>
            )
            closeModal()
        })
    }

    return (
        <Modal title="Add graph to dashboard" onDismiss={closeModal}>
            <form onSubmit={save}>
                <label>Panel name on dashboard</label>
                <input
                    name="name"
                    autoFocus
                    required
                    type="text"
                    className="form-control"
                    placeholder="Users who did x"
                    calue={name}
                    onChange={e => setName(e.target.value)}
                />
                <br />
                <button type="submit" className="btn btn-success">
                    Add panel to dashboard
                </button>
            </form>
        </Modal>
    )
}
