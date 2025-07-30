import { useState } from 'react'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, POSTHOG_EVENT_PROMOTED_PROPERTIES } from '~/taxonomy/taxonomy'
import { EventType } from '~/types'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ErrorDisplay } from '../Errors/ErrorDisplay'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { Link } from 'lib/lemon-ui/Link'
import { AIEventExpanded } from 'scenes/session-recordings/player/inspector/components/AIEventItems'
import { AutocaptureImageTab, autocaptureToImage } from 'lib/utils/autocapture-previews'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { useValues } from 'kea'
import { eventPropertyFilteringLogic } from 'scenes/session-recordings/player/inspector/components/eventPropertyFilteringLogic'

export const EventPropertyTabs = ({ event }: { event: Omit<EventType, 'distinct_id'> }): JSX.Element => {
    const isAIEvent = event.event === '$ai_generation' || event.event === '$ai_span' || event.event === '$ai_trace'

    const isErrorEvent = event.event === '$exception'

    const { filterProperties } = useValues(eventPropertyFilteringLogic)

    const [activeTab, setActiveTab] = useState<
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
    >(isAIEvent ? 'conversation' : isErrorEvent ? 'error_display' : 'properties')

    const promotedKeys = POSTHOG_EVENT_PROMOTED_PROPERTIES[event.event]

    const properties = {}
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
            } else if (key.startsWith('$exception')) {
                errorProperties[key] = event.properties[key]
            } else {
                properties[key] = event.properties[key]
            }
        }
    }

    return (
        <LemonTabs
            size="small"
            activeKey={activeTab}
            onChange={(newKey) => setActiveTab(newKey)}
            tabs={[
                isErrorEvent && {
                    key: 'error_display',
                    label: 'Exception',
                    content: <ErrorDisplay eventProperties={event.properties} eventId={event.id} />,
                },
                {
                    key: 'properties',
                    label: 'Properties',
                    content: <SimpleKeyValueList item={filterProperties(properties)} promotedKeys={promotedKeys} />,
                },
                {
                    key: 'flags',
                    label: 'Flags',
                    content: <SimpleKeyValueList item={featureFlagProperties} promotedKeys={promotedKeys} />,
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
                // Add conversation tab for $ai_generation events
                isAIEvent
                    ? {
                          key: 'conversation',
                          label: 'Conversation',
                          content: <AIEventExpanded event={event} />,
                      }
                    : null,
                Object.keys(setProperties).length > 0
                    ? {
                          key: '$set_properties',
                          label: 'Person properties',
                          content: (
                              <SimpleKeyValueList
                                  item={setProperties}
                                  promotedKeys={promotedKeys}
                                  header={
                                      <p>
                                          Person properties sent with this event. Will replace any property value that
                                          may have been set on this person profile before now.{' '}
                                          <Link to="https://posthog.com/docs/getting-started/person-properties">
                                              Learn more
                                          </Link>
                                      </p>
                                  }
                              />
                          ),
                      }
                    : null,
                Object.keys(setOnceProperties).length > 0
                    ? {
                          key: '$set_once_properties',
                          label: 'Set once person properties',
                          content: (
                              <SimpleKeyValueList
                                  item={setOnceProperties}
                                  promotedKeys={promotedKeys}
                                  header={
                                      <p>
                                          "Set once" person properties sent with this event. Will replace any property
                                          value that have never been set on this person profile before now.{' '}
                                          <Link to="https://posthog.com/docs/getting-started/person-properties">
                                              Learn more
                                          </Link>
                                      </p>
                                  }
                              />
                          ),
                      }
                    : null,
                Object.keys(errorProperties).length > 0
                    ? {
                          key: 'exception_properties',
                          label: 'Exception properties',
                          content: (
                              <SimpleKeyValueList
                                  item={errorProperties}
                                  promotedKeys={promotedKeys}
                                  header={
                                      <p>
                                          PostHog uses properties that start with $exception to carry information about
                                          errors.
                                      </p>
                                  }
                              />
                          ),
                      }
                    : null,
                Object.keys(debugProperties).length > 0
                    ? {
                          key: 'debug_properties',
                          label: 'Debug properties',
                          content: (
                              <SimpleKeyValueList
                                  item={debugProperties}
                                  promotedKeys={promotedKeys}
                                  header={<p>PostHog uses some properties to help debug issues with the SDKs.</p>}
                              />
                          ),
                      }
                    : null,
                {
                    key: 'raw',
                    label: 'Raw',
                    content: (
                        <pre className="text-xs text-secondary whitespace-pre-wrap">
                            {JSON.stringify(event.properties, null, 2)}
                        </pre>
                    ),
                },
            ]}
        />
    )
}
