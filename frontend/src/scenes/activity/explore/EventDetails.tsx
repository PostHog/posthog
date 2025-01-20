import './EventDetails.scss'

import { LemonButton } from '@posthog/lemon-ui'
import { LemonTableProps } from '@posthog/lemon-ui'
import { LemonTabs } from '@posthog/lemon-ui'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { JSONViewer } from 'lib/components/JSONViewer'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { dayjs } from 'lib/dayjs'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, KNOWN_PROMOTED_PROPERTY_PARENTS } from 'lib/taxonomy'
import { pluralize } from 'lib/utils'
import { AutocaptureImageTab, autocaptureToImage } from 'lib/utils/event-property-utls'
import { useState } from 'react'
import { ConversationDisplay } from 'scenes/llm-observability/ConversationDisplay/ConversationDisplay'

import { EventType, PropertyDefinitionType } from '~/types'

interface EventDetailsProps {
    event: EventType
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
}

export function EventDetails({ event, tableProps }: EventDetailsProps): JSX.Element {
    const [showSystemProps, setShowSystemProps] = useState(false)
    const [activeTab, setActiveTab] = useState(
        event.event === '$ai_generation' ? 'conversation' : event.event === '$exception' ? 'exception' : 'properties'
    )

    const displayedEventProperties = {}
    const visibleSystemProperties = {}
    const featureFlagProperties = {}
    let systemPropsCount = 0
    for (const key of Object.keys(event.properties)) {
        if (CORE_FILTER_DEFINITIONS_BY_GROUP.events[key] && CORE_FILTER_DEFINITIONS_BY_GROUP.events[key].system) {
            systemPropsCount += 1
            if (showSystemProps) {
                visibleSystemProperties[key] = event.properties[key]
            }
        }
        if (!CORE_FILTER_DEFINITIONS_BY_GROUP.events[key] || !CORE_FILTER_DEFINITIONS_BY_GROUP.events[key].system) {
            if (key.startsWith('$feature') || key === '$active_feature_flags') {
                featureFlagProperties[key] = event.properties[key]
            } else {
                displayedEventProperties[key] = event.properties[key]
            }
        }
    }

    const tabs = [
        {
            key: 'properties',
            label: 'Properties',
            content: (
                <div className="mx-3">
                    <PropertiesTable
                        type={PropertyDefinitionType.Event}
                        properties={{
                            ...('timestamp' in event ? { $timestamp: dayjs(event.timestamp).toISOString() } : {}),
                            ...displayedEventProperties,
                            ...visibleSystemProperties,
                        }}
                        useDetectedPropertyType={true}
                        tableProps={tableProps}
                        filterable
                        searchable
                        parent={event.event as KNOWN_PROMOTED_PROPERTY_PARENTS}
                    />
                    {systemPropsCount > 0 && (
                        <LemonButton className="mb-2" onClick={() => setShowSystemProps(!showSystemProps)} size="small">
                            {showSystemProps ? 'Hide' : 'Show'}{' '}
                            {pluralize(systemPropsCount, 'system property', 'system properties')}
                        </LemonButton>
                    )}
                </div>
            ),
        },
        {
            key: 'metadata',
            label: 'Metadata',
            content: (
                <div className="mx-3 -mt-4">
                    <PropertiesTable
                        type={PropertyDefinitionType.Meta}
                        properties={{
                            event: event.event,
                            distinct_id: event.distinct_id,
                            timestamp: event.timestamp,
                        }}
                        sortProperties
                        tableProps={tableProps}
                    />
                </div>
            ),
        },
        {
            key: 'raw',
            label: 'Raw',
            content: (
                <div className="mx-3 -mt-3 py-2">
                    <JSONViewer src={event} name="event" collapsed={1} collapseStringsAfterLength={80} sortKeys />
                </div>
            ),
        },
    ]

    if (event.elements && event.elements.length > 0) {
        tabs.push({
            key: 'elements',
            label: 'Elements',
            content: (
                <HTMLElementsDisplay elements={event.elements} selectedText={event.properties['$selected_content']} />
            ),
        })
    }

    if (event.elements && autocaptureToImage(event.elements)) {
        tabs.push({
            key: 'image',
            label: 'Image',
            content: <AutocaptureImageTab elements={event.elements} />,
        })
    }

    if (event.event === '$exception') {
        tabs.splice(0, 0, {
            key: 'exception',
            label: 'Exception',
            content: (
                <div className="mx-3">
                    <ErrorDisplay eventProperties={event.properties} />
                </div>
            ),
        })
    } else if (event.event === '$ai_generation') {
        tabs.splice(0, 0, {
            key: 'conversation',
            label: 'Conversation',
            content: (
                <div className="mx-3 -mt-2 mb-2">
                    <ConversationDisplay eventProperties={event.properties} />
                </div>
            ),
        })
    }

    if (Object.keys(featureFlagProperties).length > 0) {
        tabs.push({
            key: 'feature_flags',
            label: 'Feature flags',
            content: (
                <div className="ml-10 mt-2">
                    <PropertiesTable
                        type={PropertyDefinitionType.Event}
                        properties={{
                            ...featureFlagProperties,
                        }}
                        useDetectedPropertyType={true}
                        tableProps={tableProps}
                        searchable
                    />
                </div>
            ),
        })
    }

    return <LemonTabs data-attr="event-details" tabs={tabs} activeKey={activeTab} onChange={setActiveTab} />
}
