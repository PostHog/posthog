import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { PaginationManual, lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { accountNotesList, accountsList } from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountNoteApi,
    PaginatedAccountListApi,
    PaginatedAccountNoteListApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { customerAnalyticsSceneLogic } from '../../customerAnalyticsSceneLogic'
import { AccountsEvents, type NotesTabFilterType } from '../Accounts/constants'
import type { accountNotesLogicType } from './accountNotesLogicType'

const RESULTS_PER_PAGE = 50
const ACCOUNT_OPTIONS_LIMIT = 50

export type AccountFilterOption = { id: string; name: string }

export const accountNotesLogic = kea<accountNotesLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'AccountNotes', 'accountNotesLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], userLogic, ['user'], customerAnalyticsSceneLogic, ['mineOnly']],
        actions: [customerAnalyticsSceneLogic, ['setMineOnly']],
    })),
    actions({
        loadAccountNotes: true,
        setSearch: (search: string) => ({ search }),
        setPage: (page: number) => ({ page }),
        setCreatedByFilter: (userIds: number[]) => ({ userIds }),
        setCreatedByCurrentUser: (value: boolean) => ({ value }),
        setAssignedToFilter: (userIds: number[]) => ({ userIds }),
        // Shortcut for the "My accounts" checkbox — resolves to the current user's id.
        setAssignedToCurrentUser: (value: boolean) => ({ value }),
        setAccountFilter: (account: AccountFilterOption | null) => ({ account }),
        setAccountSearch: (query: string) => ({ query }),
        reportFilterChange: (filterType: NotesTabFilterType) => ({ filterType }),
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
                        assigned_to: values.assignedToFilter.length ? values.assignedToFilter : undefined,
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
        assignedToFilter: [[] as number[], { setAssignedToFilter: (_, { userIds }) => userIds }],
        accountFilter: [null as AccountFilterOption | null, { setAccountFilter: (_, { account }) => account }],
        accountSearch: ['', { setAccountSearch: (_, { query }) => query }],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setSearch: () => 1,
                setCreatedByFilter: () => 1,
                setAssignedToFilter: () => 1,
                setAccountFilter: () => 1,
            },
        ],
    }),
    selectors(({ actions }) => ({
        accountNotes: [
            (s) => [s.accountNotesResponse],
            (response: PaginatedAccountNoteListApi | null): AccountNoteApi[] => response?.results ?? [],
        ],
        currentUserId: [(s) => [s.user], (user): number | null => user?.id ?? null],
        // "My notes" is a shorthand, not separate state: checked iff the created-by filter is exactly [me].
        createdByCurrentUser: [
            (s) => [s.createdByFilter, s.currentUserId],
            (createdByFilter: number[], currentUserId: number | null): boolean =>
                currentUserId !== null && createdByFilter.length === 1 && createdByFilter[0] === currentUserId,
        ],
        // "My accounts" is the same shorthand over the assigned-to filter (accounts where I'm
        // CSM or AE). Shared with the Accounts tab via customerAnalyticsSceneLogic.mineOnly.
        assignedToCurrentUser: [
            (s) => [s.assignedToFilter, s.currentUserId],
            (assignedToFilter: number[], currentUserId: number | null): boolean =>
                currentUserId !== null && assignedToFilter.length === 1 && assignedToFilter[0] === currentUserId,
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
        setCreatedByFilter: () => actions.loadAccountNotes(),
        setCreatedByCurrentUser: ({ value }) => {
            actions.setCreatedByFilter(value && values.currentUserId !== null ? [values.currentUserId] : [])
        },
        setAssignedToFilter: () => {
            actions.loadAccountNotes()
            // Keep the shared "mine only" ("My accounts") toggle in step so switching to the
            // Accounts tab reflects the same choice.
            actions.setMineOnly(values.assignedToCurrentUser)
        },
        setAssignedToCurrentUser: ({ value }) => {
            actions.setAssignedToFilter(value && values.currentUserId !== null ? [values.currentUserId] : [])
        },
        setAccountFilter: () => actions.loadAccountNotes(),
        setAccountSearch: ({ query }) => actions.loadAccountOptions({ query }),
        // Captures live in a dedicated report action (dispatched by the controls only) so the
        // "My notes"/"My accounts" shortcuts cascading into the raw filters don't double-fire events.
        reportFilterChange: ({ filterType }) => {
            const properties: Record<string, string | number | boolean> = { filter_type: filterType }
            if (filterType === 'created_by') {
                properties.is_cleared = values.createdByFilter.length === 0
                properties.user_count = values.createdByFilter.length
            } else if (filterType === 'account') {
                properties.is_cleared = values.accountFilter === null
            } else if (filterType === 'my_accounts') {
                properties.value = values.assignedToCurrentUser
                properties.is_cleared = !values.assignedToCurrentUser
            } else {
                properties.value = values.createdByCurrentUser
                properties.is_cleared = !values.createdByCurrentUser
            }
            posthog.capture(AccountsEvents.NotesTabFiltered, properties)
        },
        loadAccountNotesFailure: ({ error }) => {
            posthog.captureException(error)
            lemonToast.error('Failed to load account notes')
        },
        loadAccountOptionsFailure: ({ error }) => {
            posthog.captureException(error)
        },
    })),
    afterMount(({ actions, values }) => {
        posthog.capture(AccountsEvents.NotesTabViewed)
        // Restore the shared "My accounts" choice from the other tab. Setting the assigned-to
        // filter triggers the initial notes load, so only fall back to a bare load when it's off.
        if (values.mineOnly && values.currentUserId !== null) {
            actions.setAssignedToCurrentUser(true)
        } else {
            actions.loadAccountNotes()
        }
        actions.loadAccountOptions({ query: '' })
    }),
])
