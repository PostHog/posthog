import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { PaginationManual, lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { accountNotesList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountNoteApi,
    PaginatedAccountNoteListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountNotesLogicType } from './accountNotesLogicType'

const RESULTS_PER_PAGE = 50

export const accountNotesLogic = kea<accountNotesLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'AccountNotes', 'accountNotesLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        loadAccountNotes: true,
        setSearch: (search: string) => ({ search }),
        setPage: (page: number) => ({ page }),
    }),
    loaders(({ values }) => ({
        accountNotesResponse: [
            null as PaginatedAccountNoteListApi | null,
            {
                loadAccountNotes: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await accountNotesList(String(values.currentTeamId), {
                        search: values.search || undefined,
                        limit: RESULTS_PER_PAGE,
                        offset: (values.page - 1) * RESULTS_PER_PAGE,
                    })
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        page: [1, { setPage: (_, { page }) => page, setSearch: () => 1 }],
    }),
    selectors(({ actions }) => ({
        accountNotes: [
            (s) => [s.accountNotesResponse],
            (response: PaginatedAccountNoteListApi | null): AccountNoteApi[] => response?.results ?? [],
        ],
        pagination: [
            (s) => [s.page, s.accountNotesResponse],
            (page: number, response: PaginatedAccountNoteListApi | null): PaginationManual => ({
                controlled: true,
                pageSize: RESULTS_PER_PAGE,
                currentPage: page,
                entryCount: response?.count ?? 0,
                onBackward: () => actions.setPage(page - 1),
                onForward: () => actions.setPage(page + 1),
            }),
        ],
    })),
    listeners(({ actions }) => ({
        setSearch: () => actions.loadAccountNotes(),
        setPage: () => actions.loadAccountNotes(),
        loadAccountNotesFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to load account notes')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAccountNotes()
    }),
])
