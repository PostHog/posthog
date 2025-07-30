import './ImagePreview.scss'

import { IconShare, IconWarning } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonMenu, LemonTabs, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { HTMLElementsDisplay } from 'lib/components/HTMLElementsDisplay/HTMLElementsDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TitledSnack } from 'lib/components/TitledSnack'
import { IconLink, IconOpenInNew } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { autoCaptureEventToDescription, capitalizeFirstLetter, isString } from 'lib/utils'
import { AutocaptureImageTab, AutocapturePreviewImage, autocaptureToImage } from 'lib/utils/autocapture-previews'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { useState } from 'react'
import { insightUrlForEvent } from 'scenes/insights/utils'
import { eventPropertyFilteringLogic } from 'scenes/session-recordings/player/inspector/components/eventPropertyFilteringLogic'
import { urls } from 'scenes/urls'

import { POSTHOG_EVENT_PROMOTED_PROPERTIES } from '~/taxonomy/taxonomy'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'

import { InspectorListItemEvent } from '../playerInspectorLogic'
import { AIEventExpanded, AIEventSummary } from './AIEventItems'
import { getExceptionAttributes } from 'lib/components/Errors/utils'

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

function ExceptionTitlePill({ event }: { event: Record<string, any> }): JSX.Element {
    const errorProps = getExceptionAttributes(event.properties)
    let connector = ''
    if (!!errorProps.type && !!errorProps.value) {
        connector = ':'
    }
    return (
        <div className="flex flex-row items-center gap-1 justify-between border px-1 truncate ellipsis border-x-danger-dark bg-danger-highlight">
            <span>{errorProps.type}</span>
            <span>{connector}</span>
            <span>{errorProps.value}</span>
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
            <AutocapturePreviewImage elements={item.data.elements} properties={item.data.properties} />
        ) : item.data.event === '$ai_generation' ||
          item.data.event === '$ai_span' ||
          item.data.event === '$ai_trace' ? (
            <AIEventSummary event={item.data} />
        ) : item.data.event === '$exception' ? (
            <ExceptionTitlePill event={item.data} />
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

    const isErrorEvent = item.data.event === '$exception'

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
    >(isAIEvent ? 'conversation' : isErrorEvent ? 'error_display' : 'properties')

    const insightUrl = insightUrlForEvent(item.data)
    const { filterProperties } = useValues(eventPropertyFilteringLogic)

    const promotedKeys = POSTHOG_EVENT_PROMOTED_PROPERTIES[item.data.event]

    const properties = {}
    const featureFlagProperties = {}
    const errorProperties = {}
    const debugProperties = {}
    let setProperties = {}
    let setOnceProperties = {}

    for (const key of Object.keys(item.data.properties)) {
        if (!CORE_FILTER_DEFINITIONS_BY_GROUP.events[key] || !CORE_FILTER_DEFINITIONS_BY_GROUP.events[key].system) {
            if (CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[key].used_for_debug) {
                debugProperties[key] = item.data.properties[key]
            } else if (key.startsWith('$feature') || key === '$active_feature_flags') {
                featureFlagProperties[key] = item.data.properties[key]
            } else if (key === '$set') {
                setProperties = item.data.properties[key]
            } else if (key === '$set_once') {
                setOnceProperties = item.data.properties[key]
            } else if (key.startsWith('$exception')) {
                errorProperties[key] = item.data.properties[key]
            } else {
                properties[key] = item.data.properties[key]
            }
        }
    }

    // Get trace ID for linking to LLM trace view
    const traceId = item.data.properties.$ai_trace_id
    const traceParams = item.data.id && item.data.event !== '$ai_trace' ? { event: item.data.id } : {}
    const traceUrl = traceId ? urls.llmObservabilityTrace(traceId, traceParams) : null

    return (
        <div data-attr="item-event" className="font-light w-full">
            <div className="px-2 py-1 text-xs border-t">
                <div className="flex justify-end gap-2">
                    {item.data.event === '$exception' && '$exception_issue_id' in item.data.properties ? (
                        <LemonButton
                            targetBlank
                            sideIcon={<IconOpenInNew />}
                            data-attr="replay-inspector-issue-link"
                            to={urls.errorTrackingIssue(
                                item.data.properties.$exception_issue_id,
                                item.data.properties.$exception_fingerprint
                            )}
                            size="xsmall"
                        >
                            View issue
                        </LemonButton>
                    ) : null}
                    <LemonMenu
                        items={[
                            {
                                label: 'Copy link to event',
                                icon: <IconLink />,
                                onClick: () => {
                                    void copyToClipboard(
                                        urls.absolute(
                                            urls.currentProject(urls.event(String(item.data.id), item.data.timestamp))
                                        ),
                                        'link to event'
                                    )
                                },
                            },
                            item.data.event === '$exception' && '$exception_issue_id' in item.data.properties
                                ? {
                                      label: 'Copy link to issue',
                                      icon: <IconWarning />,
                                      onClick: () => {
                                          void copyToClipboard(
                                              urls.absolute(
                                                  urls.currentProject(
                                                      urls.errorTrackingIssue(
                                                          item.data.properties.$exception_issue_id,
                                                          item.data.properties.$exception_fingerprint
                                                      )
                                                  )
                                              ),
                                              'issue link'
                                          )
                                      },
                                  }
                                : null,
                            insightUrl
                                ? {
                                      label: 'Try out in Insights',
                                      icon: <IconOpenInNew />,
                                      to: insightUrl,
                                      targetBlank: true,
                                  }
                                : null,
                            traceUrl
                                ? {
                                      label: 'View LLM Trace',
                                      icon: <IconLink />,
                                      to: traceUrl,
                                      targetBlank: true,
                                  }
                                : null,
                        ]}
                        buttonSize="xsmall"
                    >
                        <div className="recordings-event-share-actions">
                            <LemonButton size="xsmall" icon={<IconShare />}>
                                Share
                            </LemonButton>
                        </div>
                    </LemonMenu>
                </div>
                <LemonDivider dashed />

                {item.data.fullyLoaded ? (
                    <LemonTabs
                        size="small"
                        activeKey={activeTab}
                        onChange={(newKey) => setActiveTab(newKey)}
                        tabs={[
                            item.data.event === '$exception' && {
                                key: 'error_display',
                                label: 'Exception',
                                content: <ErrorDisplay eventProperties={item.data.properties} eventId={item.data.id} />,
                            },
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
                                      content: (
                                          <AutocaptureImageTab
                                              elements={item.data.elements}
                                              properties={item.data.properties}
                                          />
                                      ),
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
                                                      Person properties sent with this event. Will replace any property
                                                      value that may have been set on this person profile before now.{' '}
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
                                                      "Set once" person properties sent with this event. Will replace
                                                      any property value that have never been set on this person profile
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
                                                      PostHog uses properties that start with $exception to carry
                                                      information about errors.
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
                                              header={
                                                  <p>
                                                      PostHog uses some properties to help debug issues with the SDKs.
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
