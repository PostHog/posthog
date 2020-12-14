import React, { useState } from 'react'
import { Button } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { router } from 'kea-router'

interface Props {
    item: DashboardItemAttributes
}

interface DashboardItemAttributes {
    type: string
    entity: TrendPayload | FunnelPayload
}

interface TrendPayload {
    filters: Record<string, any>
    annotations: Array<Record<string, any>>
}

interface FunnelPayload {
    name: string
}

export function SaveToDashboard(props: Props): JSX.Element {
    const { item } = props
    const [openModal, setOpenModal] = useState<boolean>(false)
    const [{ fromItem, fromItemName, fromDashboard }] = useState(router.values.hashParams)
    let _name: string
    let _filters: Record<string, any> | null = null
    let _annotations: Array<Record<string, any>> | null = null

    if ('filters' in item.entity) {
        _filters = item.entity.filters
        _annotations = item.entity.annotations
    } else {
        _name = item.entity.name
    }

    return (
        <span className="save-to-dashboard">
            {openModal && (
                <SaveToDashboardModal
                    closeModal={(): void => setOpenModal(false)}
                    name={_name}
                    filters={_filters}
                    fromItem={fromItem}
                    fromDashboard={fromDashboard}
                    fromItemName={fromItemName}
                    annotations={_annotations}
                />
            )}
            <Button onClick={(): void => setOpenModal(true)} type="primary" data-attr="save-to-dashboard-button">
                {fromItem ? 'Update Dashboard' : 'Add to dashboard'}
            </Button>
        </span>
    )
}
