import React from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import moment from 'moment'
import { EventElements } from 'scenes/events/EventElements'
import { Tabs, Button } from 'antd'

import { createActionFromEvent, recurseSelector } from './createActionFromEvent'
const { TabPane } = Tabs

export function EventDetails({ event }) {
    return (
        <>
            {event.elements.length > 0 && recurseSelector(event.elements, '', 0)}
            <Button
                onClick={() => createActionFromEvent(event, 0)}
                style={{ float: 'right', zIndex: 9999 }}
                type="primary"
            >
                Create action from event
            </Button>
            <Tabs
                style={{ float: 'left', width: '100%', marginTop: -40 }}
                data-attr="event-details"
                defaultActiveKey="properties"
                animated={false}
            >
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
        </>
    )
}
