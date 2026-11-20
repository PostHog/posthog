import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { groupsModel } from '~/models/groupsModel'

import type { SessionListItemApi } from '../../generated/api.schemas'
import { ListEmptyState } from '../lists/components/ListEmptyState'
import { ListErrorState } from '../lists/components/ListErrorState'
import { ListTable } from '../lists/components/ListTable'
import { ListToolbar } from '../lists/components/ListToolbar'
import { listFiltersLogic } from '../lists/listFiltersLogic'
import { TraceCellLoad } from '../shared/cellLoads'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { opensTraceDrawer } from '../trace/traceDrawerRows'
import { TraceDrawerRowProps } from '../trace/TraceDrawerRowsHost'
import { SessionListRow } from './components/SessionListRow'
import { sessionCellsLogic } from './sessionCellsLogic'
import { SessionConversationHost } from './SessionConversationHost'
import { SESSION_TURNS_LIST } from './sessionConversationLogic'
import { OpenSessionStatus, SESSIONS_LIST_FILTERS, sessionsListLogic } from './sessionsListLogic'

// pinned: autocapture dashboards and tests select the list and its controls by this value and the suffixes built on it
const DATA_ATTR = 'ai-observability-sessions-list'
const SESSION_LINK = '[data-attr="ai-observability-session-link"]'
const UNREAD: TraceCellLoad<never> = { status: 'loading' }

/** The pane while there is no open session to show the conversation of. */
function OpenSessionPlaceholder({
    status,
    onRetry,
    onClose,
}: {
    status: Exclude<OpenSessionStatus, 'ready'>
    onRetry: () => void
    onClose: () => void
}): JSX.Element {
    if (status === 'loading') {
        return (
            <div className="flex flex-col gap-3 p-4" aria-busy="true">
                <LemonSkeleton className="h-6 w-1/2" />
                <LemonSkeleton className="h-10 w-2/3 self-end" />
                <LemonSkeleton className="h-24 w-4/5" />
            </div>
        )
    }
    if (status === 'not_found') {
        return (
            <ListEmptyState
                title="Session not found"
                description="Check the link, or pick a session from the list."
                action={{ label: 'Close session', onClick: onClose, 'data-attr': `${DATA_ATTR}-close-session` }}
            />
        )
    }
    if (status === 'failed') {
        return (
            <ListErrorState
                title="Couldn't load this session"
                description="Try again. If it keeps happening, contact support."
                retry={{ onClick: onRetry, 'data-attr': `${DATA_ATTR}-retry-session` }}
            />
        )
    }
    return (
        <ListEmptyState title="No session open" description="Pick a session from the list to read its conversation." />
    )
}

export function SessionsListHost(): JSX.Element {
    const {
        items,
        state,
        refreshing,
        canShowPrevious,
        canShowNext,
        filterTestAccounts,
        searchEnabled,
        openSessionId,
        openItem,
        openSessionStatus,
        sessionHref,
    } = useValues(sessionsListLogic)
    const { showPreviousPage, showNextPage, reload, openSession, lookUpSession } = useActions(sessionsListLogic)
    const { filters, searchDraft } = useValues(listFiltersLogic(SESSIONS_LIST_FILTERS))
    const { setPropertyFilters, setFilterTestAccounts, setSearchDraft, resetFilters } = useActions(
        listFiltersLogic(SESSIONS_LIST_FILTERS)
    )
    const { titles, people } = useValues(sessionCellsLogic)
    const { dateFrom, dateTo } = useValues(shellScopeLogic)
    const { setDateRange } = useActions(shellScopeLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { openTraceId } = useValues(traceDrawerLogic({ listId: SESSION_TURNS_LIST }))
    const columns: LemonTableColumns<SessionListItemApi> = useMemo(
        () => [
            {
                key: 'session',
                title: 'Session',
                render: (_, item) => (
                    <SessionListRow
                        item={item}
                        title={titles.get(item.firstTraceId) ?? UNREAD}
                        person={people.get(item.firstTraceId) ?? UNREAD}
                        isOpen={item.id === openSessionId}
                        href={sessionHref(item.id)}
                    />
                ),
            },
        ],
        [titles, people, openSessionId, sessionHref]
    )
    const onRow = useCallback(
        (item: SessionListItemApi): TraceDrawerRowProps => ({
            className: 'cursor-pointer',
            onClickCapture: (event) => {
                // The same click rule as a trace row: the title link or the row itself, never the person's own link.
                if (opensTraceDrawer(event, SESSION_LINK, true)) {
                    event.preventDefault()
                    event.stopPropagation()
                    openSession(item.id)
                }
            },
        }),
        [openSession]
    )

    return (
        <div className="flex flex-col gap-3">
            <ListToolbar
                search={searchDraft}
                onSearchChange={searchEnabled ? setSearchDraft : undefined}
                searchPlaceholder="Search inputs and outputs"
                filters={
                    <PropertyFilters
                        propertyFilters={filters.propertyFilters}
                        onChange={setPropertyFilters}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                        pageKey={DATA_ATTR}
                    />
                }
                testAccounts={
                    <TestAccountFilterSwitch
                        checked={filterTestAccounts}
                        onChange={setFilterTestAccounts}
                        size="small"
                    />
                }
                dateRange={<DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDateRange} size="small" />}
                onReload={reload}
                reloading={state === 'loading' || refreshing}
                data-attr={DATA_ATTR}
            />
            {/* The panes scroll on their own, so the split fills the window below the scene header and the toolbar. */}
            <div className="flex h-[calc(100vh-16.5rem)] min-h-100 gap-3">
                <div className="w-75 shrink-0 overflow-y-auto">
                    <ListTable<SessionListItemApi>
                        state={state}
                        columns={columns}
                        rows={items}
                        rowKey={(item) => item.id}
                        refreshing={refreshing}
                        onRow={onRow}
                        onPrevious={canShowPrevious ? showPreviousPage : undefined}
                        onNext={canShowNext ? showNextPage : undefined}
                        emptyState={
                            <ListEmptyState
                                title="No sessions in this date range"
                                description="Pick a wider date range to see older sessions."
                            />
                        }
                        emptyFilteredState={
                            <ListEmptyState
                                title="No sessions match"
                                description="Change or clear the filters to see more sessions."
                                action={{
                                    label: 'Clear filters',
                                    onClick: resetFilters,
                                    'data-attr': `${DATA_ATTR}-clear-filters`,
                                }}
                            />
                        }
                        errorState={
                            <ListErrorState
                                title="Couldn't load sessions"
                                description="Try again. If it keeps happening, contact support."
                                retry={{ onClick: reload, 'data-attr': `${DATA_ATTR}-retry` }}
                            />
                        }
                        data-attr={DATA_ATTR}
                    />
                </div>
                <div className="min-w-0 flex-1 rounded border border-primary bg-surface-primary">
                    {openItem ? (
                        <SessionConversationHost
                            key={openItem.id}
                            session={openItem}
                            title={titles.get(openItem.firstTraceId) ?? UNREAD}
                            person={people.get(openItem.firstTraceId) ?? UNREAD}
                            aroundTraceId={openTraceId}
                        />
                    ) : (
                        <OpenSessionPlaceholder
                            status={openSessionStatus === 'ready' ? 'loading' : openSessionStatus}
                            onRetry={() => openSessionId !== null && lookUpSession(openSessionId)}
                            onClose={() => openSession(null)}
                        />
                    )}
                </div>
            </div>
            <TraceDrawerHost listId={SESSION_TURNS_LIST} />
        </div>
    )
}
