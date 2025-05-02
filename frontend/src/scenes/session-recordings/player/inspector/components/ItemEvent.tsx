import './ImagePreview.scss'

import { LemonButton, LemonDivider, LemonTabs, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TitledSnack } from 'lib/components/TitledSnack'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { autoCaptureEventToDescription, capitalizeFirstLetter, isString } from 'lib/utils'
import { AutocaptureImageTab, AutocapturePreviewImage, autocaptureToImage } from 'lib/utils/event-property-utls'
import { useState } from 'react'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { eventPropertyFilteringLogic } from 'scenes/session-recordings/player/inspector/components/eventPropertyFilteringLogic'

import { POSTHOG_EVENT_PROMOTED_PROPERTIES } from '~/taxonomy/taxonomy'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

import { InspectorListItemEvent } from '../playerInspectorLogic'
import { AIEventExpanded, AIEventSummary } from './AIEventItems'

export interface ItemEventProps {
    item: InspectorListItemEvent
}

function WebVitalEventSummary({ event }: { event: Record<string, any> }): JSX.Element {
    return (
        <>
            {event ? (
                <TitledSnack
                    type={event.rating === 'good' ? 'success' : 'default'}
                    title={event.name}
                    titleSuffix=""
                    value={
                        <>
                            {event.rating}: {event.value.toFixed(2)}
                        </>
                    }
                />
            ) : null}
        </>
    )
}

function SummarizeWebVitals({ properties }: { properties: Record<string, any> }): JSX.Element {
    const { $web_vitals_FCP_event, $web_vitals_CLS_event, $web_vitals_INP_event, $web_vitals_LCP_event } = properties

    return (
        <div className="flex gap-1 items-center">
            <WebVitalEventSummary event={$web_vitals_FCP_event} />
            <WebVitalEventSummary event={$web_vitals_CLS_event} />
            <WebVitalEventSummary event={$web_vitals_INP_event} />
            <WebVitalEventSummary event={$web_vitals_LCP_event} />
        </div>
    )
}

export function ItemEvent({ item }: ItemEventProps): JSX.Element {
    const subValue =
        item.data.event === '$pageview' ? (
            item.data.properties.$pathname || item.data.properties.$current_url
        ) : item.data.event === '$screen' ? (
            item.data.properties.$screen_name
        ) : item.data.event === '$web_vitals' ? (
            <SummarizeWebVitals properties={item.data.properties} />
        ) : item.data.elements.length ? (
            <AutocapturePreviewImage elements={item.data.elements} />
        ) : item.data.event === '$ai_generation' ||
          item.data.event === '$ai_span' ||
          item.data.event === '$ai_trace' ? (
            <AIEventSummary event={item.data} />
        ) : null

    return (
        <div data-attr="item-event" className="font-light w-full">
            <div className="flex flex-row w-full justify-between gap-2 items-center px-2 py-1 text-xs cursor-pointer">
                <div className="truncate">
                    <PropertyKeyInfo
                        className="font-medium"
                        disablePopover={true}
                        disableIcon={true}
                        ellipsis={true}
                        value={capitalizeFirstLetter(autoCaptureEventToDescription(item.data))}
                        type={TaxonomicFilterGroupType.Events}
                    />
                    {item.data.event === '$autocapture' ? <span className="text-secondary">(Autocapture)</span> : null}
                </div>
                {subValue ? (
                    <div className="text-secondary truncate" title={isString(subValue) ? subValue : undefined}>
                        {subValue}
                    </div>
                ) : null}
            </div>
        </div>
    )
}

export function ItemEventDetail({ item }: ItemEventProps): JSX.Element {
    // // Check if this is an LLM-related event
    const isAIEvent =
        item.data.event === '$ai_generation' || item.data.event === '$ai_span' || item.data.event === '$ai_trace'

    const [activeTab, setActiveTab] = useState<
        | 'properties'
        | 'flags'
        | 'image'
        | 'elements'
        | '$set_properties'
        | '$set_once_properties'
        | 'raw'
        | 'conversation'
    >(isAIEvent ? 'conversation' : 'properties')

    const insightUrl = insightUrlForEvent(item.data)
    const { filterProperties } = useValues(eventPropertyFilteringLogic)

    const promotedKeys = POSTHOG_EVENT_PROMOTED_PROPERTIES[item.data.event]

    const properties = {}
    const featureFlagProperties = {}
    let setProperties = {}
    let setOnceProperties = {}

    for (const key of Object.keys(item.data.properties)) {
        if (!CORE_FILTER_DEFINITIONS_BY_GROUP.events[key] || !CORE_FILTER_DEFINITIONS_BY_GROUP.events[key].system) {
            if (key.startsWith('$feature') || key === '$active_feature_flags') {
                featureFlagProperties[key] = item.data.properties[key]
            } else if (key === '$set') {
                setProperties = item.data.properties[key]
            } else if (key === '$set_once') {
                setOnceProperties = item.data.properties[key]
            } else {
                properties[key] = item.data.properties[key]
            }
        }
    }

    // Get trace ID for linking to LLM trace view
    const traceId = item.data.properties.$ai_trace_id
    const traceUrl = traceId
        ? `/llm-observability/traces/${traceId}${
              item.data.id && item.data.event !== '$ai_trace' ? `?event=${item.data.id}` : ''
          }`
        : null

    return (
        <div data-attr="item-event" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t">
                {insightUrl || traceUrl ? (
                    <>
                        <div className="flex justify-end gap-2">
                            {insightUrl && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    sideIcon={<IconOpenInNew />}
                                    data-attr="recordings-event-to-insights"
                                    to={insightUrl}
                                    targetBlank
                                >
                                    Try out in Insights
                                </LemonButton>
                            )}
                            {traceUrl && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    sideIcon={<IconOpenInNew />}
                                    data-attr="recordings-event-to-llm-trace"
                                    to={traceUrl}
                                    targetBlank
                                >
                                    View LLM Trace
                                </LemonButton>
                            )}
                        </div>
                        <LemonDivider dashed />
                    </>
                ) : null}

                {item.data.fullyLoaded ? (
                    item.data.event === '$exception' ? (
                        <ErrorDisplay eventProperties={item.data.properties} />
                    ) : (
                        <LemonTabs
                            size="small"
                            activeKey={activeTab}
                            onChange={(newKey) => setActiveTab(newKey)}
                            tabs={[
                                {
                                    key: 'properties',
                                    label: 'Properties',
                                    content: (
                                        <SimpleKeyValueList
                                            item={filterProperties(properties)}
                                            promotedKeys={promotedKeys}
                                        />
                                    ),
                                },
                                {
                                    key: 'flags',
                                    label: 'Flags',
                                    content: (
                                        <SimpleKeyValueList item={featureFlagProperties} promotedKeys={promotedKeys} />
                                    ),
                                },
                                item.data.elements && item.data.elements.length > 0
                                    ? {
                                          key: 'elements',
                                          label: 'Elements',
                                          content: (
                                              <HTMLElementsDisplay
                                                  size="xsmall"
                                                  elements={item.data.elements}
                                                  selectedText={item.data.properties['$selected_content']}
                                              />
                                          ),
                                      }
                                    : null,
                                autocaptureToImage(item.data.elements)
                                    ? {
                                          key: 'image',
                                          label: 'Image',
                                          content: <AutocaptureImageTab elements={item.data.elements} />,
                                      }
                                    : null,
                                // Add conversation tab for $ai_generation events
                                isAIEvent
                                    ? {
                                          key: 'conversation',
                                          label: 'Conversation',
                                          content: <AIEventExpanded event={item.data} />,
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
                                                          Person properties sent with this event. Will replace any
                                                          property value that may have been set on this person profile
                                                          before now.{' '}
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
                                                          "Set once" person properties sent with this event. Will
                                                          replace any property value that have never been set on this
                                                          person profile before now.{' '}
                                                          <Link to="https://posthog.com/docs/getting-started/person-properties">
                                                              Learn more
                                                          </Link>
                                                      </p>
                                                  }
                                              />
                                          ),
                                      }
                                    : null,
                                {
                                    key: 'raw',
                                    label: 'Raw',
                                    content: (
                                        <pre className="text-xs text-secondary whitespace-pre-wrap">
                                            {JSON.stringify(item.data.properties, null, 2)}
                                        </pre>
                                    ),
                                },
                            ]}
                        />
                    )
                ) : (
                    <div className="text-secondary flex gap-1 items-center">
                        <Spinner textColored />
                        Loading...
                    </div>
                )}
            </div>
        </div>
    )
}
