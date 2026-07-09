import { actions, afterMount, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { PaginationManual, Sorting } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { notebookPanelLogic } from 'scenes/notebooks/NotebookPanel/notebookPanelLogic'
import { defaultNotebookContent } from 'scenes/notebooks/utils'
import { teamLogic } from 'scenes/teamLogic'

import { accountsNotebooksCreate, accountsNotebooksList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountNotebookApi,
    PaginatedAccountNotebookListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountNotebooksLogicType } from './accountNotebooksLogicType'
import { AccountsEvents } from './constants'

export const NOTES_PER_PAGE = 5

export const DEFAULT_NOTES_SORTING: Sorting = { columnKey: 'created_at', order: -1 }

export interface AccountNotebooksLogicProps {
    accountId: string
}

// Maps the table's sorting state onto the backend's whitelisted `ordering` param.
function sortingToOrdering(sorting: Sorting | null): string | undefined {
    if (!sorting) {
        return undefined
    }
    return sorting.order === -1 ? `-${sorting.columnKey}` : sorting.columnKey
}

export const accountNotebooksLogic = kea<accountNotebooksLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountNotebooksLogic', key]),
    props({} as AccountNotebooksLogicProps),
    key((props) => props.accountId),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [notebookPanelLogic, ['selectNotebook']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSorting: (sorting: Sorting | null) => ({ sorting }),
        setPage: (page: number) => ({ page }),
        createNote: true,
    }),
    loaders(({ props, values }) => ({
        notebooksResponse: [
            null as PaginatedAccountNotebookListApi | null,
            {
                loadNotebooks: async (_ = null, breakpoint) => {
                    const projectId = String(values.currentTeamId)
                    try {
                        const response = await accountsNotebooksList(projectId, props.accountId, {
                            limit: NOTES_PER_PAGE,
                            offset: (values.page - 1) * NOTES_PER_PAGE,
                            search: values.searchTerm.trim() || undefined,
                            ordering: sortingToOrdering(values.sorting),
                        })
                        breakpoint()
                        return response
                    } catch (error) {
                        if (!isBreakpoint(error as Error)) {
                            posthog.captureException(error as Error, {
                                scope: 'accountNotebooksLogic.loadNotebooks',
                            })
                            lemonToast.error('Failed to load account notes')
                        }
                        throw error
                    }
                },
            },
        ],
        createdNote: [
            null as AccountNotebookApi | null,
            {
                createNote: async () => {
                    const projectId = String(values.currentTeamId)
                    try {
                        return await accountsNotebooksCreate(projectId, props.accountId, {
                            content: defaultNotebookContent(),
                        })
                    } catch (error) {
                        posthog.captureException(error as Error, {
                            scope: 'accountNotebooksLogic.createNote',
                        })
                        lemonToast.error('Failed to create note')
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        sorting: [DEFAULT_NOTES_SORTING as Sorting | null, { setSorting: (_, { sorting }) => sorting }],
        page: [1, { setPage: (_, { page }) => page }],
    }),
    selectors(({ actions }) => ({
        notebooks: [(s) => [s.notebooksResponse], (response): AccountNotebookApi[] | null => response?.results ?? null],
        notebooksCount: [(s) => [s.notebooksResponse], (response): number => response?.count ?? 0],
        pagination: [
            (s) => [s.page, s.notebooksCount],
            (page, count): PaginationManual => ({
                controlled: true,
                pageSize: NOTES_PER_PAGE,
                currentPage: page,
                entryCount: count,
                onBackward: () => actions.setPage(page - 1),
                onForward: () => actions.setPage(page + 1),
            }),
        ],
    })),
    listeners(({ actions, values }) => ({
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(300)
            posthog.capture(AccountsEvents.NotesSearched, {
                has_query: values.searchTerm.trim().length > 0,
                query_length: values.searchTerm.trim().length,
            })
            actions.setPage(1)
        },
        setSorting: ({ sorting }) => {
            posthog.capture(AccountsEvents.NotesSorted, {
                column: sorting?.columnKey ?? null,
                direction: sorting ? (sorting.order === -1 ? 'desc' : 'asc') : 'cleared',
            })
            actions.setPage(1)
        },
        setPage: () => {
            actions.loadNotebooks()
        },
        createNoteSuccess: ({ createdNote }) => {
            if (!createdNote) {
                return
            }
            posthog.capture(AccountsEvents.NoteCreated, { notebook_short_id: createdNote.short_id })
            actions.selectNotebook(createdNote.short_id, { autofocus: 'end' })
            // A new note sorts to page 1 (default -created_at); reset there so it's visible in the table.
            actions.setPage(1)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNotebooks()
    }),
])
