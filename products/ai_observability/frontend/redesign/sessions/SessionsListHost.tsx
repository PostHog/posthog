import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

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
import { OpenSessionPlaceholder } from './components/OpenSessionPlaceholder'
import { SessionListRow } from './components/SessionListRow'
import { sessionCellsLogic } from './sessionCellsLogic'
import { SessionConversationHost } from './SessionConversationHost'
import { SESSION_TURNS_LIST, sessionConversationLogic } from './sessionConversationLogic'
import { SESSIONS_LIST_FILTERS, sessionsListLogic } from './sessionsListLogic'

// pinned: autocapture dashboards and tests select the list and its controls by this value and the suffixes built on it
const DATA_ATTR = 'ai-observability-sessions-list'
const SESSION_LINK = '[data-attr="ai-observability-session-link"]'
const UNREAD: TraceCellLoad<never> = { status: 'loading' }

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
        openSessionTimestamp,
        openSessionNeighbours,
        openSessionPageHref,
        sessionHref,
    } = useValues(sessionsListLogic)
    const { showPreviousPage, showNextPage, reload, openSession, lookUpSession, clearFilters } =
        useActions(sessionsListLogic)
    const { filters, searchDraft } = useValues(listFiltersLogic(SESSIONS_LIST_FILTERS))
    const { setPropertyFilters, setSearchDraft } = useActions(listFiltersLogic(SESSIONS_LIST_FILTERS))
    const { titles, people } = useValues(sessionCellsLogic)
    const { dateFrom, dateTo } = useValues(shellScopeLogic)
    const { setDateRange, setFilterTestAccounts } = useActions(shellScopeLogic)
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
                        title={titles.get(item.id) ?? UNREAD}
                        person={people.get(item.id) ?? UNREAD}
                        isOpen={item.id === openSessionId}
                        href={sessionHref(item)}
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
                    openSession(item)
                }
            },
        }),
        [openSession]
    )

    // The list's reload reads the open session's facts again, so its turns are read again with them.
    const reloadListAndConversation = (): void => {
        reload()
        if (openSessionId !== null) {
            sessionConversationLogic.findMounted(openSessionId)?.actions.reload()
        }
    }

    const stepTo = (session: SessionListItemApi | null | undefined): (() => void) | null =>
        session ? () => openSession(session) : null

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
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
                onReload={reloadListAndConversation}
                reloading={state === 'loading' || refreshing}
                data-attr={DATA_ATTR}
            />
            {/* The panes scroll on their own. Side by side they fill the height the scene has left, and where both no
                longer fit they stack, the list above the conversation. */}
            <div className="@container flex min-h-0 flex-1 flex-col">
                <div className="flex min-h-0 flex-1 flex-col gap-3 @3xl:min-h-100 @3xl:flex-row">
                    <div className="max-h-60 shrink-0 overflow-y-auto @3xl:max-h-none @3xl:w-75">
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
                                        onClick: clearFilters,
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
                    <div className="min-h-100 min-w-0 flex-1 rounded border border-primary bg-surface-primary @3xl:min-h-0">
                        {openSessionId !== null &&
                        (openSessionStatus === 'loading' || openSessionStatus === 'ready') ? (
                            <SessionConversationHost
                                key={openSessionId}
                                sessionId={openSessionId}
                                timestamp={openSessionTimestamp}
                                session={openItem}
                                title={titles.get(openSessionId) ?? UNREAD}
                                person={people.get(openSessionId) ?? UNREAD}
                                aroundTraceId={openTraceId}
                                listNavigation={{
                                    fullPageHref: openSessionPageHref,
                                    listed: openSessionNeighbours !== null,
                                    onPrevious: stepTo(openSessionNeighbours?.previous),
                                    onNext: stepTo(openSessionNeighbours?.next),
                                }}
                            />
                        ) : (
                            <OpenSessionPlaceholder
                                status={
                                    openSessionStatus === 'not_found' || openSessionStatus === 'failed'
                                        ? openSessionStatus
                                        : 'none'
                                }
                                onRetry={() => openSessionId !== null && lookUpSession(openSessionId)}
                                onClose={() => openSession(null)}
                            />
                        )}
                    </div>
                </div>
            </div>
            <TraceDrawerHost listId={SESSION_TURNS_LIST} />
        </div>
    )
}
