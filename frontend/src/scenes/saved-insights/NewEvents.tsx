import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import { EventDefinition } from '~/types'

import { EventRow } from './EventRow'
import { newEventsLogic } from './newEventsLogic'

export function NewEvents(): JSX.Element {
    const { newEvents, newEventsLoading, newEventsLoadedError } = useValues(newEventsLogic)
    const { loadNewEvents } = useActions(newEventsLogic)

    return (
        <CompactList
            title={
                <div className="flex items-center gap-1">
                    New events
                    <Tooltip title="Events that PostHog saw for the first time recently.">
                        <IconInfo className="text-muted text-base" />
                    </Tooltip>
                </div>
            }
            viewAllURL={urls.eventDefinitions()}
            viewAllDataAttr="insights-home-tab-new-events-view-all"
            loading={newEventsLoading}
            error={newEventsLoadedError}
            errorMessage={{
                title: "Couldn't load new events",
                description: 'Something went wrong loading this list.',
                buttonText: 'Retry',
                buttonOnClick: loadNewEvents,
            }}
            emptyMessage={{
                title: 'No events found',
                description: 'Set up event capture to see events here.',
                buttonText: 'View all events',
                buttonTo: urls.eventDefinitions(),
            }}
            items={newEvents.slice(0, 5)}
            renderRow={(event: EventDefinition) => <EventRow key={event.id} event={event} />}
            contentHeightBehavior="fit-content"
        />
    )
}
