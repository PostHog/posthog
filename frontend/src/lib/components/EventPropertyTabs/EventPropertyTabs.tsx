import { useState } from 'react'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, POSTHOG_EVENT_PROMOTED_PROPERTIES } from '~/taxonomy/taxonomy'
import { EventType, RecordingEventType } from '~/types'
import { LemonTab, LemonTabs, LemonTabsProps } from 'lib/lemon-ui/LemonTabs'
import { AutocaptureImageTab, autocaptureToImage } from 'lib/utils/autocapture-previews'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { useValues } from 'kea'

import { eventPropertyFilteringLogic } from 'lib/components/EventPropertyTabs/eventPropertyFilteringLogic'
import { INTERNAL_EXCEPTION_PROPERTY_KEYS } from '@posthog/products-error-tracking/frontend/utils'
import { dayjs } from 'lib/dayjs'

export interface TabContentComponentFnProps {
    event: EventType | RecordingEventType
    properties: Record<string, any>
    promotedKeys?: string[]
    tabKey: EventPropertyTabKey
}

type EventPropertyTabKey =
    | 'properties'
    | 'flags'
    | 'image'
    | 'elements'
    | '$set_properties'
    | '$set_once_properties'
    | 'raw'
    | 'conversation'
    | 'exception_properties'
    | 'error_display'
    | 'debug_properties'
    | 'metadata'

export const EventPropertyTabs = ({
    event,
    tabContentComponentFn,
    ...lemonTabsProps
}: {
    event: EventType | RecordingEventType
    tabContentComponentFn: (props: TabContentComponentFnProps) => JSX.Element
    dataAttr?: LemonTabsProps<EventPropertyTabKey>['data-attr']
    size?: LemonTabsProps<EventPropertyTabKey>['size']
    barClassName?: LemonTabsProps<EventPropertyTabKey>['barClassName']
}): JSX.Element => {
    const isAIGenerationEvent = event.event === '$ai_generation'
    const isAIEvent = isAIGenerationEvent || event.event === '$ai_span' || event.event === '$ai_trace'

    const isErrorEvent = event.event === '$exception'

    const { filterProperties } = useValues(eventPropertyFilteringLogic)

    const [activeTab, setActiveTab] = useState<EventPropertyTabKey>(
        isAIEvent ? 'conversation' : isErrorEvent ? 'error_display' : 'properties'
    )

    const promotedKeys = POSTHOG_EVENT_PROMOTED_PROPERTIES[event.event]

    let properties = {}
    const featureFlagProperties = {}
    const errorProperties = {}
    const debugProperties = {}
    let setProperties = {}
    let setOnceProperties = {}

    for (const key of Object.keys(event.properties)) {
        if (!CORE_FILTER_DEFINITIONS_BY_GROUP.events[key] || !CORE_FILTER_DEFINITIONS_BY_GROUP.events[key].system) {
            if (CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[key]?.used_for_debug) {
                debugProperties[key] = event.properties[key]
            } else if (key.startsWith('$feature') || key === '$active_feature_flags') {
                featureFlagProperties[key] = event.properties[key]
            } else if (key === '$set') {
                setProperties = event.properties[key] ?? {}
            } else if (key === '$set_once') {
                setOnceProperties = event.properties[key] ?? {}
            } else if (INTERNAL_EXCEPTION_PROPERTY_KEYS.includes(key)) {
                errorProperties[key] = event.properties[key]
            } else {
                properties[key] = event.properties[key]
            }
        }
    }
    properties = {
        ...('timestamp' in event ? { $timestamp: dayjs(event.timestamp).toISOString() } : {}),
        ...filterProperties(properties),
    }

    const tabs: (LemonTab<EventPropertyTabKey> | null | false)[] = [
        isErrorEvent && {
            key: 'error_display',
            label: 'Exception',
            content: tabContentComponentFn({ event, properties: errorProperties, tabKey: 'error_display' }),
        },
        isAIEvent
            ? {
                  key: 'conversation',
                  label: 'Conversation',
                  content: tabContentComponentFn({ event, properties, tabKey: 'conversation' }),
              }
            : null,
        {
            key: 'properties',
            label: 'Properties',
            content: tabContentComponentFn({ event, properties, promotedKeys, tabKey: 'properties' }),
        },
        {
            key: 'metadata',
            label: 'Metadata',
            content: tabContentComponentFn({
                event,
                promotedKeys,
                properties: {
                    event: event.event,
                    distinct_id: event.distinct_id,
                    timestamp: event.timestamp,
                },
                tabKey: 'metadata',
            }),
        },
        {
            key: 'flags',
            label: 'Flags',
            content: tabContentComponentFn({ event, properties: featureFlagProperties, promotedKeys, tabKey: 'flags' }),
        },
        event.elements && event.elements.length > 0
            ? {
                  key: 'elements',
                  label: 'Elements',
                  content: (
                      <HTMLElementsDisplay
                          size="xsmall"
                          elements={event.elements}
                          selectedText={event.properties['$selected_content']}
                      />
                  ),
              }
            : null,
        autocaptureToImage(event.elements)
            ? {
                  key: 'image',
                  label: 'Image',
                  content: <AutocaptureImageTab elements={event.elements} properties={event.properties} />,
              }
            : null,
        Object.keys(setProperties).length > 0
            ? {
                  key: '$set_properties',
                  label: 'Person properties',
                  content: tabContentComponentFn({
                      properties: setProperties,
                      event,
                      promotedKeys,
                      tabKey: '$set_properties',
                  }),
              }
            : null,
        Object.keys(setOnceProperties).length > 0
            ? {
                  key: '$set_once_properties',
                  label: 'Set once person properties',
                  content: tabContentComponentFn({
                      properties: setOnceProperties,
                      event,
                      promotedKeys,
                      tabKey: '$set_once_properties',
                  }),
              }
            : null,
        Object.keys(errorProperties).length > 0
            ? {
                  key: 'exception_properties',
                  label: 'Exception properties',
                  content: tabContentComponentFn({
                      properties: errorProperties,
                      event,
                      promotedKeys,
                      tabKey: 'exception_properties',
                  }),
              }
            : null,
        Object.keys(debugProperties).length > 0
            ? {
                  key: 'debug_properties',
                  label: 'Debug properties',
                  content: tabContentComponentFn({
                      properties: debugProperties,
                      event,
                      promotedKeys,
                      tabKey: 'debug_properties',
                  }),
              }
            : null,
        {
            key: 'raw',
            label: 'Raw',
            content: tabContentComponentFn({ event, properties, tabKey: 'raw' }),
        },
    ]
    return (
        <LemonTabs
            {...lemonTabsProps}
            activeKey={activeTab}
            onChange={(newKey: EventPropertyTabKey) => setActiveTab(newKey)}
            tabs={tabs}
        />
    )
}
