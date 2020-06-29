import React, { useState } from 'react'
import { Button } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { router } from 'kea-router'

export function SaveToDashboard({ name, type, filters, annotations }) {
    const [openModal, setOpenModal] = useState(false)
    const [{ fromItem, fromItemName, fromDashboard }] = useState(router.values.hashParams)

    return (
        <span className="save-to-dashboard">
            {openModal && (
                <SaveToDashboardModal
                    closeModal={() => setOpenModal(false)}
                    name={name}
                    type={type}
                    filters={filters}
                    fromItem={fromItem}
                    fromDashboard={fromDashboard}
                    fromItemName={fromItemName}
                    annotations={annotations}
                />
            )}
            <Button onClick={() => setOpenModal(true)} type="primary" data-attr="save-to-dashboard-button">
                {fromItem && type !== 'FunnelViz' ? 'Update Dashboard' : 'Add to dashboard'}
            </Button>
        </span>
    )
}
