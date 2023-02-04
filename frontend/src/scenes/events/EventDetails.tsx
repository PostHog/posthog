import { useState } from 'react'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { HtmlElementsDisplay } from 'lib/components/HtmlElementsDisplay/HtmlElementsDisplay'
import { Tabs } from 'antd'
import { EventJSON } from 'scenes/events/EventJSON'
import { EventType } from '../../types'
import { Properties } from '@posthog/plugin-scaffold'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { pluralize } from 'lib/utils'
import { LemonTableProps } from 'lib/lemon-ui/LemonTable'
import ReactJson from 'react-json-view'

const { TabPane } = Tabs

interface EventDetailsProps {
    event: EventType
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
    /** Used under data exploration tables */
    useReactJsonView?: boolean
}

export function EventDetails({ event, tableProps, useReactJsonView }: EventDetailsProps): JSX.Element {
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
                    <HtmlElementsDisplay elements={event.elements} />
                </TabPane>
            )}
        </Tabs>
    )
}
