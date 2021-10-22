import React, { useState } from 'react'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import dayjs from 'dayjs'
import { EventElements } from 'scenes/events/EventElements'
import { Tabs, Button } from 'antd'

import { createActionFromEvent } from './createActionFromEvent'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { EventJSON } from 'scenes/events/EventJSON'
import { EventType } from '../../types'
import { Properties } from '@posthog/plugin-scaffold'
import { useValues } from 'kea'
import { teamLogic } from '../teamLogic'

const { TabPane } = Tabs

export function EventDetails({ event }: { event: EventType }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)

    const [showHiddenProps, setShowHiddenProps] = useState(false)

    const displayedEventProperties: Properties = {}
    const visibleHiddenProperties: Properties = {}
    let hiddenPropsCount = 0
    for (const key of Object.keys(event.properties)) {
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
            {currentTeamId && (
                <Button
                    onClick={() => createActionFromEvent(currentTeamId, event, 0)}
                    style={{ float: 'right', zIndex: 1 }}
                    type="primary"
                >
                    Create action from event
                </Button>
            )}

            <Tabs
                style={{ float: 'left', width: '100%', marginTop: -40 }}
                data-attr="event-details"
                defaultActiveKey="properties"
                animated={false}
            >
                <TabPane tab="Properties" key="properties">
                    <PropertiesTable
                        properties={{
                            $timestamp: dayjs(event.timestamp).toISOString(),
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
                <TabPane tab="JSON" key="json">
                    <EventJSON event={event} />
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
