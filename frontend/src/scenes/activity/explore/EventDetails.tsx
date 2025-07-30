import './EventDetails.scss'

import { JSONViewer } from 'lib/components/JSONViewer'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTableProps } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { ConversationDisplay } from 'products/llm_observability/frontend/ConversationDisplay/ConversationDisplay'
import { useState } from 'react'
import { urls } from 'scenes/urls'

import { KNOWN_PROMOTED_PROPERTY_PARENTS } from '~/taxonomy/taxonomy'
import { EventType, PropertyDefinitionType } from '~/types'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { EventPropertyTabs } from 'lib/components/EventPropertyTabs/EventPropertyTabs'

interface EventDetailsProps {
    event: EventType
    tableProps?: Partial<LemonTableProps<Record<string, any>>>
}

export function EventDetails({ event, tableProps }: EventDetailsProps): JSX.Element {
    const [showSystemProps, setShowSystemProps] = useState(false)

    return (
        <EventPropertyTabs
            data-attr="event-details"
            size="medium"
            event={event}
            displayForEventFn={({ event, properties, tabKey }) => {
                switch (tabKey) {
                    case 'properties':
                        return (
                            <div className="mx-3">
                                <PropertiesTable
                                    type={PropertyDefinitionType.Event}
                                    properties={properties}
                                    useDetectedPropertyType={true}
                                    tableProps={tableProps}
                                    filterable
                                    searchable
                                    parent={event.event as KNOWN_PROMOTED_PROPERTY_PARENTS}
                                />
                                <LemonButton
                                    className="mb-2"
                                    onClick={() => setShowSystemProps(!showSystemProps)}
                                    size="small"
                                >
                                    {showSystemProps ? 'Hide' : 'Show'} system properties
                                </LemonButton>
                            </div>
                        )
                    case 'metadata':
                        return (
                            <div className="mx-3">
                                <PropertiesTable
                                    type={PropertyDefinitionType.Meta}
                                    properties={properties}
                                    sortProperties
                                    tableProps={tableProps}
                                />
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
                    case 'flags':
                        return (
                            <div className="ml-10 mt-2">
                                <PropertiesTable
                                    type={PropertyDefinitionType.Event}
                                    properties={properties}
                                    useDetectedPropertyType={true}
                                    tableProps={tableProps}
                                    searchable
                                />
                            </div>
                        )
                    case '$set_properties':
                        return (
                            <div className="ml-10 mt-2">
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
                            <div className="ml-10 mt-2">
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
                                    sortProperties
                                    tableProps={tableProps}
                                />
                            </div>
                        )
                }
            }}
            aiDisplayFn={({ properties }) => {
                return (
                    <div className="mx-3 -mt-2 mb-2 deprecated-space-y-2">
                        {properties.$session_id ? (
                            <div className="flex flex-row items-center gap-2">
                                <Link
                                    to={urls.replay(undefined, undefined, properties.$session_id)}
                                    className="flex flex-row gap-1 items-center"
                                >
                                    <IconOpenInNew />
                                    <span>View session recording</span>
                                </Link>
                            </div>
                        ) : null}
                        <ConversationDisplay eventProperties={properties} />
                    </div>
                )
            }}
        />
    )
}
