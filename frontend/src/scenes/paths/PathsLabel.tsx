import { Row } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ViewType } from '~/types'

export function PathCanvasLabel(): JSX.Element | null {
    const { activeView } = useValues(insightLogic)

    if (activeView !== ViewType.PATHS) {
        return null
    }

    return (
        <Row className="funnel-canvas-label" align="middle">
            <React.Fragment>
                <span className="text-muted-alt">
                    Large path items are shown by default. View smaller items by hovering over a node
                </span>
            </React.Fragment>
        </Row>
    )
}
