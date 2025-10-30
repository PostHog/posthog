import { ErrorDisplay, idFrom } from 'lib/components/Errors/ErrorDisplay'
import { ErrorPropertyTabEvent, EventPropertyTabs } from 'lib/components/EventPropertyTabs/EventPropertyTabs'
import { JSONViewer } from 'lib/components/JSONViewer'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonTableProps } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'

import { KNOWN_PROMOTED_PROPERTY_PARENTS } from '~/taxonomy/taxonomy'
import { PropertyDefinitionType } from '~/types'

import { ConversationDisplay } from 'products/llm_analytics/frontend/ConversationDisplay/ConversationDisplay'
import { EvaluationDisplay } from 'products/llm_analytics/frontend/ConversationDisplay/EvaluationDisplay'

interface EventDetailsProps {
    event: ErrorPropertyTabEvent
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
}

export function EventDetails({ event, tableProps }: EventDetailsProps): JSX.Element {
    return (
        <EventPropertyTabs
            barClassName="px-2"
            data-attr="event-details"
            size="medium"
            event={event}
            tabContentComponentFn={({ event, properties, tabKey }) => {
                switch (tabKey) {
                    case 'conversation':
                        return (
                            <div className="mx-3 -mt-2 mb-2 gap-y-2">
                                {properties.$session_id ? (
                                    <div className="flex flex-row items-center gap-2">
                                        <ViewRecordingButton
                                            sessionId={properties.$session_id}
                                            recordingStatus={properties.$recording_status}
                                            timestamp={event.timestamp}
                                            inModal={false}
                                            size="small"
                                            type="secondary"
                                            data-attr="conversation-view-session-recording-button"
                                        />
                                    </div>
                                ) : null}
                                <ConversationDisplay eventProperties={properties} />
                            </div>
                        )
                    case 'evaluation':
                        return (
                            <div className="mx-3 -mt-2 mb-2">
                                <EvaluationDisplay eventProperties={properties} />
                            </div>
                        )
                    case 'error_display':
                        return (
                            <div className="mx-3">
                                <ErrorDisplay eventProperties={properties} eventId={idFrom(event)} />
                            </div>
                        )
                    case 'exception_properties':
                        return (
                            <div className="mx-3 -mt-4">
                                <LemonBanner type="info" dismissKey="event-details-exception-properties-why-banner">
                                    These are the internal properties that PostHog uses to display information about
                                    exceptions.
                                </LemonBanner>
                                <PropertiesTable
                                    type={PropertyDefinitionType.Event}
                                    properties={properties}
                                    sortProperties
                                    tableProps={tableProps}
                                />
                            </div>
                        )
                    case '$set_properties':
                        return (
                            <div className="mx-3 -mt-4">
                                <p>
                                    Person properties sent with this event. Will replace any property value that may
                                    have been set on this person profile before now.{' '}
                                    <Link to="https://posthog.com/docs/getting-started/person-properties">
                                        Learn more
                                    </Link>
                                </p>
                                <PropertiesTable
                                    type={PropertyDefinitionType.Event}
                                    properties={properties}
                                    useDetectedPropertyType={true}
                                    tableProps={tableProps}
                                    searchable
                                />
                            </div>
                        )
                    case '$set_once_properties':
                        return (
                            <div className="mx-3 -mt-4">
                                <p>
                                    "Set once" person properties sent with this event. Will replace any property value
                                    that have never been set on this person profile before now.{' '}
                                    <Link to="https://posthog.com/docs/getting-started/person-properties">
                                        Learn more
                                    </Link>
                                </p>
                                <PropertiesTable
                                    type={PropertyDefinitionType.Event}
                                    properties={properties}
                                    useDetectedPropertyType={true}
                                    tableProps={tableProps}
                                    searchable
                                />
                            </div>
                        )
                    case 'raw':
                        return (
                            <div className="mx-3 -mt-3 py-2">
                                <JSONViewer
                                    src={event}
                                    name="event"
                                    collapsed={1}
                                    collapseStringsAfterLength={80}
                                    sortKeys
                                />
                            </div>
                        )
                    default:
                        return (
                            <div className="mx-3">
                                <PropertiesTable
                                    type={PropertyDefinitionType.Event}
                                    properties={properties}
                                    useDetectedPropertyType={['flags', 'properties'].includes(tabKey)}
                                    tableProps={tableProps}
                                    filterable={tabKey === 'properties'}
                                    sortProperties
                                    // metadata is so short, that serachable is wasted space
                                    searchable={tabKey !== 'metadata'}
                                    parent={
                                        tabKey === 'properties'
                                            ? (event.event as KNOWN_PROMOTED_PROPERTY_PARENTS)
                                            : undefined
                                    }
                                />
                            </div>
                        )
                }
            }}
        />
    )
}
