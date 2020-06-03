import React from 'react'
import { ActionsLineGraph } from 'scenes/trends/ActionsLineGraph'
import { useValues } from 'kea'
import { currentPageLogic } from '~/toolbar/currentPageLogic'

const pageViews = (url = 'http://localhost:8000/demo') => ({
    filters: {
        events: [
            {
                id: '$pageview',
                type: 'events',
                order: 0,
            },
            {
                id: '$pageview',
                math: 'dau',
                type: 'events',
                order: 1,
            },
        ],
        actions: [],
        interval: 'day',
        new_entity: [],
        properties: [
            {
                key: '$current_url',
                type: 'event',
                value: url,
            },
        ],
    },
    type: 'ActionsLineGraph',
})
export function PageViewStats() {
    const { href } = useValues(currentPageLogic)

    return (
        <div className="toolbar-block">
            <div style={{ marginBottom: 10 }}>
                <span style={{ borderBottom: '2px dashed hsla(230, 14%, 78%, 1)' }}>Last 7 days</span>
            </div>
            <ActionsLineGraph
                dashboardItemId="toolbar"
                filters={pageViews(href).filters}
                color={'white'}
                theme={'light'}
            />
        </div>
    )
}
