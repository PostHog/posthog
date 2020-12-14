import React, { useState } from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import moment from 'moment'
import { EventElements } from 'scenes/events/EventElements'
import { Tabs, Button } from 'antd'

import { createActionFromEvent } from './createActionFromEvent'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
const { TabPane } = Tabs

export function EventDetails({ event }) {
    const [showHiddenProps, setShowHiddenProps] = useState(false)

    let displayedEventProperties = {}
    let visibleHiddenProperties = {}
    let hiddenPropsCount = 0
    for (let key of Object.keys(event.properties)) {
        if (keyMapping.event[key] && keyMapping.event[key].hide) {
            hiddenPropsCount += 1
            if (showHiddenProps) {
                visibleHiddenProperties[key] = event.properties[key]
            }
        }
        if (!keyMapping.event[key] || !keyMapping.event[key].hide) {
            displayedEventProperties[key] = event.properties[key]
        }
    }

    return (
        <>
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
                            $timestamp: moment(event.timestamp).toISOString(),
                            ...displayedEventProperties,
                            ...visibleHiddenProperties,
                        }}
                    />
                    {hiddenPropsCount > 0 && (
                        <small>
                            <Button
                                style={{ margin: '8px 0 0 8px' }}
                                type="link"
                                onClick={() => setShowHiddenProps(!showHiddenProps)}
                            >
                                {hiddenPropsCount} hidden properties. Click to {showHiddenProps ? 'hide' : 'show'}.
                            </Button>
                        </small>
                    )}
                </TabPane>
                {event.elements && event.elements.length > 0 && (
                    <TabPane tab="Elements" key="elements">
                        <EventElements event={event} />
                    </TabPane>
                )}
            </Tabs>
        </>
    )
}
