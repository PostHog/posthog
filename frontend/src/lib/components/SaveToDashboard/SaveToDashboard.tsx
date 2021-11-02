import React, { useState } from 'react'
import { Button } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { DashboardItemType } from '~/types'
import { CheckSquareOutlined } from '@ant-design/icons'

interface Props {
    insight: Partial<DashboardItemType>
}

export function SaveToDashboard({ insight }: Props): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            {openModal && <SaveToDashboardModal closeModal={() => setOpenModal(false)} insight={insight} />}
            <Button
                onClick={() => setOpenModal(true)}
                type="default"
                style={{ color: 'var(--primary)' }}
                icon={!!insight.dashboard ? <CheckSquareOutlined /> : null}
                className="btn-save"
            >
                {!!insight.dashboard ? 'On dashboard' : 'Add to dashboard'}
            </Button>
        </span>
    )
}
