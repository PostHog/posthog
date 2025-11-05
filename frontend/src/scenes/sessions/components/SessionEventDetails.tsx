import { ErrorDisplay, idFrom } from 'lib/components/Errors/ErrorDisplay'
import { EventPropertyTabs } from 'lib/components/EventPropertyTabs/EventPropertyTabs'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
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
        <div className="px-2 py-1">
            <EventPropertyTabs
                size="small"
                event={event}
                tabContentComponentFn={({ event, properties, promotedKeys, tabKey }) => {
                    switch (tabKey) {
                        case 'error_display':
                            // Exception display with stack traces
                            return <ErrorDisplay eventProperties={properties} eventId={idFrom(event)} />
                        case 'raw':
                            // Raw JSON view
                            return (
                                <pre className="text-xs text-secondary whitespace-pre-wrap">
                                    {JSON.stringify(event, null, 2)}
                                </pre>
                            )
                        default:
                            // Standard properties view
                            return <SimpleKeyValueList item={properties} promotedKeys={promotedKeys} />
                    }
                }}
            />
        </div>
    )
}
