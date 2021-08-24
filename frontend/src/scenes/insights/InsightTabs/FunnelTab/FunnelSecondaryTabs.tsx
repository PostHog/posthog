import React from 'react'
import { Card, Row } from 'antd'
import { SavedFunnels } from 'scenes/insights/SavedCard'

export function FunnelSecondaryTabs(): JSX.Element | null {
    return (
        <>
            <Card
                title={<Row align="middle">Funnels Saved in Project</Row>}
                style={{ marginTop: 16, marginBottom: 16 }}
            >
                <SavedFunnels />
            </Card>
        </>
    )
}
