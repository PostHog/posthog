import { ErrorDisplay } from 'lib/components/Errors/ErrorDisplay'
import { EventPropertyTabs } from 'lib/components/EventPropertyTabs/EventPropertyTabs'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { RecordingEventType } from '~/types'

export interface SessionEventDetailsProps {
    event: RecordingEventType
}

export function SessionEventDetails({ event }: SessionEventDetailsProps): JSX.Element {
    if (!event.fullyLoaded) {
        return (
            <div className="px-4 py-3 flex items-center gap-2 text-secondary">
                <Spinner textColored />
                <span>Loading event details...</span>
            </div>
        )
    }

    return (
        <div className="mx-2">
            <EventPropertyTabs
                size="small"
                event={event}
                tabContentComponentFn={({ event, properties, promotedKeys, tabKey }) => {
                    switch (tabKey) {
                        case 'error_display':
                            const eventId =
                                ('uuid' in event ? event.uuid : null) ||
                                ('id' in event ? event.id : null) ||
                                dayjs(event.timestamp).toISOString() ||
                                `error-${event.timestamp}`
                            return <ErrorDisplay eventProperties={properties} eventId={eventId} />
                        case 'raw':
                            return (
                                <pre className="text-xs text-secondary whitespace-pre-wrap">
                                    {JSON.stringify(event, null, 2)}
                                </pre>
                            )
                        default:
                            return <SimpleKeyValueList item={properties} promotedKeys={promotedKeys} />
                    }
                }}
            />
        </div>
    )
}
