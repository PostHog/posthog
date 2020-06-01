import React from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import moment from 'moment'
import { EventElements } from 'scenes/events/EventElements'
import { Tabs } from 'antd'
const { TabPane } = Tabs

export function EventDetails({ event }) {
    return (
        <Tabs data-attr="event-details" defaultActiveKey="properties" animated={false}>
            <TabPane tab="Properties" key="properties">
                <PropertiesTable
                    properties={{
                        Timestamp: moment(event.timestamp).toISOString(),
                        ...event.properties,
                    }}
                />
            </TabPane>
            {event.elements.length > 0 && (
                <TabPane tab="Elements" key="elements">
                    <EventElements event={event} />
                </TabPane>
            )}
        </Tabs>
    )
}
