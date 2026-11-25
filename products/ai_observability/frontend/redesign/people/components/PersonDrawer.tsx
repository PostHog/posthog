import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import type {
    PersonListItemApi,
    SessionListItemApi,
    SessionPreviewApi,
    TraceListItemApi,
    TracePreviewApi,
} from '../../../generated/api.schemas'
import { ListEmptyState } from '../../lists/components/ListEmptyState'
import { ListErrorState } from '../../lists/components/ListErrorState'
import type { CellLoads, TraceCellLoad } from '../../shared/cellLoads'
import type { PersonDrawerStatus, PersonFirstSeen } from '../types'
import { PersonDrawerHeader } from './PersonDrawerHeader'
import { PersonDrawerSection } from './PersonDrawerSection'
import { RecentSessionRow } from './RecentSessionRow'
import { RecentTraceRow } from './RecentTraceRow'

// pinned: autocapture dashboards select the drawer's controls by this value and the suffixes built on it
const PERSON_DRAWER_DATA_ATTR = 'ai-observability-person-drawer'
const UNREAD: TraceCellLoad<never> = { status: 'loading' }

export interface PersonDrawerProps {
    /** Null until the person is read, and when the range does not hold them. */
    person: PersonListItemApi | null
    status: PersonDrawerStatus
    /** Null until it is asked for. */
    firstSeen: TraceCellLoad<PersonFirstSeen> | null
    recentTraces: TraceCellLoad<TraceListItemApi[]>
    traceTitles: CellLoads<TracePreviewApi>
    recentSessions: TraceCellLoad<SessionListItemApi[]>
    sessionTitles: CellLoads<SessionPreviewApi>
    onOpenTrace: (traceId: string) => void
    sessionHref: (session: SessionListItemApi) => string
    viewAllHref: string
    personHref: string | null
    onRetryPerson: () => void
    onRetryTraces: () => void
    onRetrySessions: () => void
}

export function PersonDrawer({
    person,
    status,
    firstSeen,
    recentTraces,
    traceTitles,
    recentSessions,
    sessionTitles,
    onOpenTrace,
    sessionHref,
    viewAllHref,
    personHref,
    onRetryPerson,
    onRetryTraces,
    onRetrySessions,
}: PersonDrawerProps): JSX.Element {
    if (status === 'not_found') {
        return (
            <ListEmptyState
                title="Person not found in this range"
                description="Pick a wider date range to see their activity."
            />
        )
    }
    const hidesSessions = recentSessions.status === 'ready' && recentSessions.value.length === 0
    return (
        <div className="flex flex-col gap-6">
            {status === 'error' ? (
                <ListErrorState
                    title="Couldn't load this person"
                    description="Try again. If it keeps happening, contact support."
                    retry={{ onClick: onRetryPerson, 'data-attr': `${PERSON_DRAWER_DATA_ATTR}-retry-person` }}
                />
            ) : person ? (
                <PersonDrawerHeader person={person} firstSeen={firstSeen} personHref={personHref} />
            ) : (
                <LemonSkeleton className="h-32" />
            )}
            {hidesSessions ? null : (
                <PersonDrawerSection
                    title="Recent sessions"
                    load={recentSessions}
                    empty="No sessions in this date range."
                    failedTitle="Couldn't load recent sessions"
                    retry={{ onClick: onRetrySessions, 'data-attr': `${PERSON_DRAWER_DATA_ATTR}-retry-sessions` }}
                    renderItem={(session) => (
                        <RecentSessionRow
                            key={session.id}
                            session={session}
                            title={sessionTitles.get(session.id) ?? UNREAD}
                            href={sessionHref(session)}
                        />
                    )}
                />
            )}
            <PersonDrawerSection
                title="Recent traces"
                load={recentTraces}
                empty="No traces in this date range."
                failedTitle="Couldn't load recent traces"
                retry={{ onClick: onRetryTraces, 'data-attr': `${PERSON_DRAWER_DATA_ATTR}-retry-traces` }}
                renderItem={(trace) => (
                    <RecentTraceRow
                        key={trace.id}
                        trace={trace}
                        preview={traceTitles.get(trace.id) ?? UNREAD}
                        onOpen={onOpenTrace}
                    />
                )}
                footer={
                    <LemonButton
                        className="self-start"
                        size="small"
                        type="tertiary"
                        to={viewAllHref}
                        // pinned: autocapture dashboards select the link to the person's traces by this value
                        data-attr={`${PERSON_DRAWER_DATA_ATTR}-view-all`}
                    >
                        View all in Activity
                    </LemonButton>
                }
            />
        </div>
    )
}
