import { useState } from 'react'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { EventElements } from 'scenes/events/EventElements'
import { Tabs } from 'antd'
import { EventJSON } from 'scenes/events/EventJSON'
import { EventType } from '../../types'
import { Properties } from '@posthog/plugin-scaffold'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { pluralize } from 'lib/utils'
import { LemonTableProps } from 'lib/components/LemonTable'

const { TabPane } = Tabs

interface EventDetailsProps {
    event: EventType
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
}

export function EventDetails({ event, tableProps }: EventDetailsProps): JSX.Element {
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
        <Tabs
            data-attr="event-details"
            defaultActiveKey="properties"
            style={{ float: 'left', width: '100%' }}
            tabBarStyle={{ margin: 0, paddingLeft: 12 }}
        >
            <TabPane tab="Properties" key="properties">
                <div className="ml-10">
                    <PropertiesTable
                        properties={{
                            $timestamp: dayjs(event.timestamp).toISOString(),
                            ...displayedEventProperties,
                            ...visibleHiddenProperties,
                        }}
                        useDetectedPropertyType={true}
                        tableProps={tableProps}
                    />
                    {hiddenPropsCount > 0 && (
                        <LemonButton className="mb-2" onClick={() => setShowHiddenProps(!showHiddenProps)} size="small">
                            {showHiddenProps ? 'Hide' : 'Show'}{' '}
                            {pluralize(hiddenPropsCount, 'hidden property', 'hidden properties')}
                        </LemonButton>
                    )}
                </div>
            </TabPane>
            <TabPane tab="JSON" key="json">
                <div className="px-2">
                    <EventJSON event={event} />
                </div>
            </TabPane>
            {event.elements && event.elements.length > 0 && (
                <TabPane tab="Elements" key="elements">
                    <EventElements event={event} />
                </TabPane>
            )}
        </Tabs>
    )
}
