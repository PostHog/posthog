import React, { useState } from 'react'
import { Button, TooltipProps } from 'antd'
import { SaveToDashboardModal } from './SaveToDashboardModal'
import { router } from 'kea-router'
import { Tooltip } from 'lib/components/Tooltip'

interface Props {
    item: DashboardItemAttributes
    displayComponent?: JSX.Element // Show custom component instead of default `Add to dashboard` button
    tooltipOptions?: TooltipProps // Wrap button component in a tooltip with specified props
}

interface DashboardItemAttributes {
    type?: string
    entity: TrendPayload | FunnelPayload
}

interface TrendPayload {
    filters: Record<string, any>
    annotations: Array<Record<string, any>>
}

interface FunnelPayload {
    name: string
}

export function SaveToDashboard({ item, displayComponent, tooltipOptions }: Props): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const [openTooltip, setOpenTooltip] = useState<boolean>(false)
    const [{ fromItem, fromItemName, fromDashboard }] = useState(router.values.hashParams)

    let _name: string = ''
    let _filters: Record<string, any> | null = null
    let _annotations: Array<Record<string, any>> | null = null

    if ('filters' in item.entity) {
        _filters = item.entity.filters
        _annotations = item.entity.annotations
    } else {
        _name = item.entity.name
    }

    function showTooltip(): void {
        setOpenTooltip(true)
    }

    function hideTooltip(): void {
        setOpenTooltip(false)
    }

    function showModal(): void {
        setOpenModal(true)
        hideTooltip()
    }

    function hideModal(): void {
        setOpenModal(false)
    }

    const innerContent = (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            {openModal && (
                <SaveToDashboardModal
                    closeModal={hideModal}
                    name={_name}
                    filters={_filters}
                    fromItem={fromItem}
                    fromDashboard={fromDashboard}
                    fromItemName={fromItemName}
                    annotations={_annotations}
                />
            )}
            {displayComponent ? (
                <span onClick={showModal} onMouseEnter={showTooltip} onMouseLeave={hideTooltip}>
                    {displayComponent}
                </span>
            ) : (
                <Button onClick={showModal} type="primary" onMouseEnter={showTooltip} onMouseLeave={hideTooltip}>
                    {fromItem ? 'Update Dashboard' : 'Add to dashboard'}
                </Button>
            )}
        </span>
    )

    return tooltipOptions ? (
        <Tooltip {...tooltipOptions} visible={openTooltip}>
            {innerContent}
        </Tooltip>
    ) : (
        innerContent
    )
}
