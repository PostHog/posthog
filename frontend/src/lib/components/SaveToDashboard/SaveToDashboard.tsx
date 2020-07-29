import React, { useState } from 'react'
import { Button } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { router } from 'kea-router'

interface Props {
    item: DashboardItemAttributes
    disabled: boolean
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
    funnelId: string
    name: string
}

export function SaveToDashboard(props: Props): JSX.Element {
    const { item, disabled } = props
    const [openModal, setOpenModal] = useState<boolean>(false)
    const [{ fromItem, fromItemName, fromDashboard }] = useState(router.values.hashParams)

    let _name: string
    let _filters: Record<string, any> | null = null
    let _funnelId: string | null = null
    let _annotations: Array<Record<string, any>> | null = null

    const _type: string = item.type

    if ('filters' in item.entity) {
        _filters = item.entity.filters
        _annotations = item.entity.annotations
    } else {
        _funnelId = item.entity.funnelId
        _name = item.entity.name
    }

    return (
        <span className="save-to-dashboard">
            {openModal && (
                <SaveToDashboardModal
                    closeModal={(): void => setOpenModal(false)}
                    name={_name}
                    type={_type}
                    filters={_filters}
                    funnelId={_funnelId}
                    fromItem={fromItem}
                    fromDashboard={fromDashboard}
                    fromItemName={fromItemName}
                    annotations={_annotations}
                />
            )}
            <Button
                disabled={disabled}
                onClick={(): void => setOpenModal(true)}
                type="primary"
                data-attr="save-to-dashboard-button"
            >
                {fromItem && _type !== 'FunnelViz' ? 'Update Dashboard' : 'Add to dashboard'}
            </Button>
        </span>
    )
}
