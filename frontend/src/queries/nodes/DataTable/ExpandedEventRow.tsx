import { Suspense } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { EventType } from '~/types'

// Event details render AI conversations and survey responses, which a table needs only once a row expands.
const EventDetails = lazyWithRetry(() =>
    import('scenes/activity/explore/EventDetails').then((m) => ({ default: m.EventDetails }))
)

export function ExpandedEventRow({ event }: { event: EventType }): JSX.Element {
    return (
        // The query's ErrorBoundary is nearer than the scene's, so without this a stale chunk never
        // reloads. The fallback keeps the table if the reload already ran.
        <ChunkLoadErrorBoundary
            fallback={() => (
                <LemonBanner
                    type="warning"
                    action={{ children: 'Reload page', onClick: () => window.location.reload() }}
                >
                    Couldn't load the event details. Reload the page to try again.
                </LemonBanner>
            )}
        >
            <Suspense fallback={<Spinner />}>
                <EventDetails event={event} />
            </Suspense>
        </ChunkLoadErrorBoundary>
    )
}
