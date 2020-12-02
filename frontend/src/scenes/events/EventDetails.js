import React, { useState } from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import moment from 'moment'
import { EventElements } from 'scenes/events/EventElements'
import { Tabs, Button } from 'antd'

import { createActionFromEvent } from './createActionFromEvent'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
const { TabPane } = Tabs

export function EventDetails({ event }) {
    const [showHiddenProps, setShowHiddenProps] = useState(false)
    const slicedEvent = event.event[0] == '$' ? event.event.slice(1) : event.event

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

            <Link
                to={`/insights?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24${slicedEvent}%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&properties=`}
            >
                <Button style={{ float: 'right', zIndex: 9999, marginRight: 3 }} type="primary">
                    analyze this event
                </Button>
            </Link>

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
