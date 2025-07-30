import { useState } from 'react'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, POSTHOG_EVENT_PROMOTED_PROPERTIES } from '~/taxonomy/taxonomy'
import { EventType } from '~/types'
import { LemonTab, LemonTabs, LemonTabsProps } from 'lib/lemon-ui/LemonTabs'
import { ErrorDisplay } from '../Errors/ErrorDisplay'
import { AutocaptureImageTab, autocaptureToImage } from 'lib/utils/autocapture-previews'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { useValues } from 'kea'

import { eventPropertyFilteringLogic } from 'lib/components/EventPropertyTabs/eventPropertyFilteringLogic'
import { INTERNAL_EXCEPTION_PROPERTY_KEYS } from 'products/error_tracking/frontend/utils'
import { dayjs } from 'lib/dayjs'

export interface DisplayForEventFnProps {
    event: Omit<EventType, 'distinct_id'>
    properties: Record<string, any>
    promotedKeys?: string[]
    tabKey?: EventPropertyTabKey
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
    dataAttr,
    size,
    event,
    aiDisplayFn,
    displayForEventFn,
}: {
    event: Omit<EventType, 'distinct_id'>
    displayForEventFn: (displayArgs: DisplayForEventFnProps) => JSX.Element
    aiDisplayFn: (displayArgs: DisplayForEventFnProps) => JSX.Element
    dataAttr?: LemonTabsProps<EventPropertyTabKey>['data-attr']
    size?: LemonTabsProps<EventPropertyTabKey>['size']
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
            content: (
                <ErrorDisplay
                    eventProperties={event.properties}
                    // fallback on timestamp as uuid is optional
                    eventId={event.uuid ?? event.timestamp ?? 'error'}
                    // what do we do about margin in the events table?
                    // should have <div className="mx-3">
                />
            ),
        },
        // Add conversation tab for $ai_generation events
        isAIEvent
            ? {
                  key: 'conversation',
                  label: 'Conversation',
                  content: aiDisplayFn({ event, properties }),
              }
            : null,
        {
            key: 'properties',
            label: 'Properties',
            content: displayForEventFn({ event, properties, promotedKeys, tabKey: 'properties' }),
        },
        {
            key: 'metadata',
            label: 'Metadata',
            content: displayForEventFn({
                event,
                promotedKeys,
                properties: {
                    event: event.event,
                    // ah, recordings don't add this... do we need it?
                    // distinct_id: event.distinct_id,
                    timestamp: event.timestamp,
                },
                tabKey: 'metadata',
            }),
        },
        {
            key: 'flags',
            label: 'Flags',
            content: displayForEventFn({ event, properties: featureFlagProperties, promotedKeys, tabKey: 'flags' }),
        },
        event.elements && event.elements.length > 0
            ? {
                  key: 'elements',
                  label: 'Elements',
                  content: (
                      <HTMLElementsDisplay
                          // todo: need to not be xsmall for events table
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
                  // TODO but how
                  // header={
                  //                 <p>
                  //                     Person properties sent with this event. Will replace any property value that
                  //                     may have been set on this person profile before now.{' '}
                  //                     <Link to="https://posthog.com/docs/getting-started/person-properties">
                  //                         Learn more
                  //                     </Link>
                  //                 </p>
                  //             }
                  content: displayForEventFn({
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
                  content:
                      // TODO but how
                      // header={
                      //                <p>
                      //                     "Set once" person properties sent with this event. Will replace any property
                      //                     value that have never been set on this person profile before now.{' '}
                      //                     <Link to="https://posthog.com/docs/getting-started/person-properties">
                      //                         Learn more
                      //                     </Link>
                      //                 </p>
                      //             }
                      displayForEventFn({
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
                  content: displayForEventFn({
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
                  content:
                      // header={<p>PostHog uses some properties to help debug issues with the SDKs.</p>}
                      displayForEventFn({
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
            content: displayForEventFn({ event, properties, tabKey: 'raw' }),
        },
    ]
    return (
        <LemonTabs
            data-attr={dataAttr}
            size={size}
            activeKey={activeTab}
            onChange={(newKey: EventPropertyTabKey) => setActiveTab(newKey)}
            tabs={tabs}
        />
    )
}
