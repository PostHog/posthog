import React, { useState } from 'react'
import { Button } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'

export function SaveToDashboard({ name, type, filters }) {
    const [openModal, setOpenModal] = useState(false)

    return (
        <span className="save-to-dashboard">
            {openModal && (
                <SaveToDashboardModal
                    closeModal={() => setOpenModal(false)}
                    name={name}
                    type={type}
                    filters={filters}
                />
            )}
            <Button onClick={() => setOpenModal(true)} type="primary">
                Add to dashboard
            </Button>
        </span>
    )
}
