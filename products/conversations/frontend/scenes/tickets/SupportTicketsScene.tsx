import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useMemo, useRef } from 'react'

import { LemonButton, LemonCheckbox, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { useBulkSelection } from 'lib/lemon-ui/LemonTable/useBulkSelection'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ComposeTicketButton } from '../../components/ComposeTicket'
import { ScenesTabs } from '../../components/ScenesTabs'
import { TicketListFilters } from '../../components/TicketListFilters/TicketListFilters'
import { supportEmptyState } from '../../emptyState/supportEmptyState'
import { type Ticket } from '../../types'
import { SUPPORT_TICKETS_PAGE_SIZE, supportTicketsSceneLogic } from './supportTicketsSceneLogic'
import { buildTicketColumns } from './ticketColumns'
import { ticketColumnsLogic } from './ticketColumnsLogic'

export const scene: SceneExport = {
    component: SupportTicketsScene,
    logic: supportTicketsSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
    emptyState: supportEmptyState,
}

interface SupportTicketsTableProps {
    embedded?: boolean
}

export function SupportTicketsTable({ embedded = false }: SupportTicketsTableProps): JSX.Element {
    const logic = useMountedLogic(supportTicketsSceneLogic)
    const {
        tickets,
        ticketsLoading,
        currentPage,
        totalCount,
        sorting,
        selectedTicketIds,
        searchQuery,
        hasActiveFilters,
    } = useValues(logic)
    const { setCurrentPage, setSorting, setSelectedTicketIds, clearFiltersKeepingSearch } = useActions(logic)
    const { visibleColumns } = useValues(ticketColumnsLogic)
    const { push } = useActions(router)
    const { searchParams } = useValues(router)
    const { currentTeam } = useValues(teamLogic)
    const aiEnabled = !!currentTeam?.conversations_settings?.ai_suggestions_enabled

    const getKey = useMemo(() => (t: Ticket) => t.id, [])
    const bulk = useBulkSelection<Ticket, string>({ pageRecords: tickets, getKey })
    // `bulk` is a fresh object every render, but its members are individually stable
    // (callbacks/useState/useMemo or primitives). Destructure so hook deps reference the
    // stable members instead of the unstable wrapper object.
    const {
        selectedKeys,
        clearSelection,
        isSomeOnPageSelected,
        isAllOnPageSelected,
        toggleAllOnPage,
        selectedKeysSet,
        toggleRow,
    } = bulk

    useEffect(() => {
        setSelectedTicketIds(selectedKeys)
    }, [selectedKeys, setSelectedTicketIds])

    // Clear hook selection only when kea's selection is reset *externally* (e.g. after a bulk
    // update or page reload). We detect that as a non-empty -> empty transition. Reacting to
    // `selectedTicketIds.length === 0` alone would also fire during the brief window right after
    // the first selection, before the effect above has pushed `selectedKeys` into kea — which
    // would immediately wipe the selection the user just made.
    const prevSelectedTicketIdCount = useRef(selectedTicketIds.length)
    useEffect(() => {
        const wasSelected = prevSelectedTicketIdCount.current > 0
        prevSelectedTicketIdCount.current = selectedTicketIds.length
        if (wasSelected && selectedTicketIds.length === 0 && selectedKeys.length > 0) {
            clearSelection()
        }
    }, [selectedTicketIds, selectedKeys, clearSelection])

    const columns = useMemo<LemonTableColumns<Ticket>>(() => {
        const checkboxCol: LemonTableColumns<Ticket>[number] = {
            key: '__select__' as any,
            width: 32,
            title: (
                <LemonCheckbox
                    checked={isSomeOnPageSelected ? 'indeterminate' : isAllOnPageSelected}
                    onChange={toggleAllOnPage}
                    stopPropagation
                />
            ),
            render: (_, ticket: Ticket, recordIndex: number) => (
                <LemonCheckbox
                    checked={selectedKeysSet.has(ticket.id)}
                    onChange={(_value, event) =>
                        toggleRow(ticket.id, recordIndex, (event.nativeEvent as MouseEvent).shiftKey ?? false)
                    }
                    stopPropagation
                />
            ),
        }
        return [checkboxCol, ...buildTicketColumns(visibleColumns, { aiEnabled, embedded })]
    }, [
        visibleColumns,
        embedded,
        aiEnabled,
        isSomeOnPageSelected,
        isAllOnPageSelected,
        toggleAllOnPage,
        selectedKeysSet,
        toggleRow,
    ])

    const emptyState =
        searchQuery && hasActiveFilters ? (
            <div className="flex flex-col items-center gap-2 py-2">
                <span>No tickets match your search with the current filters applied.</span>
                <LemonButton type="secondary" size="small" onClick={() => clearFiltersKeepingSearch()}>
                    Search again without filters
                </LemonButton>
            </div>
        ) : (
            'No tickets'
        )

    return (
        <LemonTable<Ticket>
            dataSource={tickets}
            rowKey="id"
            emptyState={emptyState}
            loading={ticketsLoading}
            // Keep rows clickable while a background refresh is in flight; the loading overlay
            // otherwise captures pointer events and blocks navigation on every reload.
            disableTableWhileLoading={false}
            embedded={embedded}
            sorting={sorting}
            onSort={(newSorting) => setSorting(newSorting)}
            noSortingCancellation
            pagination={{
                controlled: true,
                currentPage,
                pageSize: SUPPORT_TICKETS_PAGE_SIZE,
                entryCount: totalCount,
                onBackward: currentPage > 1 ? () => setCurrentPage(currentPage - 1) : undefined,
                onForward:
                    currentPage * SUPPORT_TICKETS_PAGE_SIZE < totalCount
                        ? () => setCurrentPage(currentPage + 1)
                        : undefined,
            }}
            onRow={(ticket) => {
                // Carry the active filters / saved view (the list's query string) onto the
                // ticket URL so the ticket's back arrow can return to this exact view. Skip it
                // when embedded (e.g. the person side panel), where the host page's query
                // string isn't the ticket filters.
                const ticketUrl = combineUrl(
                    urls.supportTicketDetail(ticket.ticket_number),
                    embedded ? {} : searchParams
                ).url
                return {
                    onClick: (e: React.MouseEvent) => {
                        if (e.metaKey || e.ctrlKey) {
                            e.preventDefault()
                            e.stopPropagation()
                            newInternalTab(ticketUrl)
                        } else {
                            push(ticketUrl)
                        }
                    },
                    onAuxClick: (e: React.MouseEvent) => {
                        if (e.button === 1) {
                            e.preventDefault()
                            e.stopPropagation()
                            newInternalTab(ticketUrl)
                        }
                    },
                }
            }}
            rowClassName={(ticket) =>
                clsx({
                    'bg-primary-alt-highlight': ticket.unread_team_count > 0,
                })
            }
            columns={columns}
        />
    )
}

export function SupportTicketsScene(): JSX.Element {
    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
                actions={<ComposeTicketButton />}
            />
            <ScenesTabs />
            <TicketListFilters />
            <SupportTicketsTable />
        </SceneContent>
    )
}
