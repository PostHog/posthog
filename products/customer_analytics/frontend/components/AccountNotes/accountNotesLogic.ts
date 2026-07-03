import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { PaginationManual, lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { accountNotesList, accountsList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountNoteApi,
    PaginatedAccountListApi,
    PaginatedAccountNoteListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountsEvents, type NotesTabFilterType } from '../Accounts/constants'
import type { accountNotesLogicType } from './accountNotesLogicType'

const RESULTS_PER_PAGE = 50
const ACCOUNT_OPTIONS_LIMIT = 50

export type AccountFilterOption = { id: string; name: string }

export const accountNotesLogic = kea<accountNotesLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'AccountNotes', 'accountNotesLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        loadAccountNotes: true,
        setSearch: (search: string) => ({ search }),
        setPage: (page: number) => ({ page }),
        setCreatedByFilter: (userIds: number[]) => ({ userIds }),
        setAccountFilter: (account: AccountFilterOption | null) => ({ account }),
        setAccountSearch: (query: string) => ({ query }),
    }),
    loaders(({ values }) => ({
        accountNotesResponse: [
            null as PaginatedAccountNoteListApi | null,
            {
                loadAccountNotes: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await accountNotesList(String(values.currentTeamId), {
                        search: values.search || undefined,
                        account_id: values.accountFilter?.id,
                        created_by: values.createdByFilter.length ? values.createdByFilter : undefined,
                        limit: RESULTS_PER_PAGE,
                        offset: (values.page - 1) * RESULTS_PER_PAGE,
                    })
                    breakpoint()
                    return response
                },
            },
        ],
        accountOptionsResponse: [
            null as PaginatedAccountListApi | null,
            {
                loadAccountOptions: async ({ query }: { query: string }, breakpoint) => {
                    await breakpoint(300)
                    const response = await accountsList(String(values.currentTeamId), {
                        search: query || undefined,
                        limit: ACCOUNT_OPTIONS_LIMIT,
                    })
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
        createdByFilter: [[] as number[], { setCreatedByFilter: (_, { userIds }) => userIds }],
        accountFilter: [null as AccountFilterOption | null, { setAccountFilter: (_, { account }) => account }],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setSearch: () => 1,
                setCreatedByFilter: () => 1,
                setAccountFilter: () => 1,
            },
        ],
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
        accountOptions: [
            (s) => [s.accountOptionsResponse, s.accountFilter],
            (
                response: PaginatedAccountListApi | null,
                accountFilter: AccountFilterOption | null
            ): { key: string; label: string }[] => {
                const options = (response?.results ?? []).map((account) => ({
                    key: account.id,
                    label: account.name,
                }))
                // Keep the selected account visible even when it's outside the current search page.
                if (accountFilter && !options.some((option) => option.key === accountFilter.id)) {
                    options.unshift({ key: accountFilter.id, label: accountFilter.name })
                }
                return options
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        // Analytics capture is debounced so only the settled query reports, never per keystroke;
        // no raw search text is logged (PII convention).
        setSearch: async (_, breakpoint) => {
            actions.loadAccountNotes()
            await breakpoint(500)
            posthog.capture(AccountsEvents.NotesTabSearched, {
                has_query: !!values.search,
                query_length: values.search.length,
            })
        },
        setPage: () => actions.loadAccountNotes(),
        setCreatedByFilter: ({ userIds }) => {
            actions.loadAccountNotes()
            posthog.capture(AccountsEvents.NotesTabFiltered, {
                filter_type: 'created_by' satisfies NotesTabFilterType,
                is_cleared: userIds.length === 0,
                user_count: userIds.length,
            })
        },
        setAccountFilter: ({ account }) => {
            actions.loadAccountNotes()
            posthog.capture(AccountsEvents.NotesTabFiltered, {
                filter_type: 'account' satisfies NotesTabFilterType,
                is_cleared: account === null,
            })
        },
        setAccountSearch: ({ query }) => actions.loadAccountOptions({ query }),
        loadAccountNotesFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to load account notes')
        },
        loadAccountOptionsFailure: ({ error }) => {
            posthog.captureException(error)
        },
    })),
    afterMount(({ actions }) => {
        posthog.capture(AccountsEvents.NotesTabViewed)
        actions.loadAccountNotes()
        actions.loadAccountOptions({ query: '' })
    }),
])
