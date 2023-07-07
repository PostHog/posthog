import { useState } from 'react'
import { KEY_MAPPING } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { Tabs } from 'antd'
import { EventJSON } from 'scenes/events/EventJSON'
import { EventType, PropertyDefinitionType } from '../../types'
import { Properties } from '@posthog/plugin-scaffold'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils'
import { LemonTableProps } from 'lib/lemon-ui/LemonTable'
import ReactJson from 'react-json-view'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'

const { TabPane } = Tabs

interface EventDetailsProps {
    event: EventType
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
    /** Used under data exploration tables */
    useReactJsonView?: boolean
}

export function EventDetails({ event, tableProps, useReactJsonView }: EventDetailsProps): JSX.Element {
    const [showSystemProps, setShowSystemProps] = useState(false)

    const displayedEventProperties: Properties = {}
    const visibleSystemProperties: Properties = {}
    let systemPropsCount = 0
    for (const key of Object.keys(event.properties)) {
        if (KEY_MAPPING.event[key] && KEY_MAPPING.event[key].system) {
            systemPropsCount += 1
            if (showSystemProps) {
                visibleSystemProperties[key] = event.properties[key]
            }
        }
        if (!KEY_MAPPING.event[key] || !KEY_MAPPING.event[key].system) {
            displayedEventProperties[key] = event.properties[key]
        }
    }

    return (
        <Tabs
            data-attr="event-details"
            defaultActiveKey={event.event === '$exception' ? 'exception' : 'properties'}
            style={{ float: 'left', width: '100%' }}
            tabBarStyle={{ margin: 0, paddingLeft: 12 }}
        >
            <TabPane tab="Properties" key="properties">
                <div className="ml-10 mt-2">
                    <PropertiesTable
                        type={PropertyDefinitionType.Event}
                        properties={{
                            $timestamp: dayjs(event.timestamp).toISOString(),
                            ...displayedEventProperties,
                            ...visibleSystemProperties,
                        }}
                        useDetectedPropertyType={true}
                        tableProps={tableProps}
                        filterable
                        searchable
                    />
                    {systemPropsCount > 0 && (
                        <LemonButton className="mb-2" onClick={() => setShowSystemProps(!showSystemProps)} size="small">
                            {showSystemProps ? 'Hide' : 'Show'}{' '}
                            {pluralize(systemPropsCount, 'system property', 'system properties')}
                        </LemonButton>
                    )}
                </div>
            </TabPane>
            <TabPane tab="JSON" key="json">
                <div className={useReactJsonView ? 'px-4 py-4' : 'px-2'}>
                    {useReactJsonView ? (
                        <ReactJson src={event} name={'event'} collapsed={1} collapseStringsAfterLength={80} sortKeys />
                    ) : (
                        <EventJSON event={event} />
                    )}
                </div>
            </TabPane>

            {event.elements && event.elements.length > 0 && (
                <TabPane tab="Elements" key="elements">
                    <HTMLElementsDisplay elements={event.elements} />
                </TabPane>
            )}

            {event.event === '$exception' && (
                <TabPane tab="Exception" key="exception">
                    <div className="ml-10 my-2">
                        <ErrorDisplay event={event} />
                    </div>
                </TabPane>
            )}
        </Tabs>
    )
}
