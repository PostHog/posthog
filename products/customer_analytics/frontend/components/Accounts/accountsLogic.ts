import { actions, afterMount, connect, isBreakpoint, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { accountsList } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { accountsLogicType } from './accountsLogicType'

export const ACCOUNTS_PAGE_SIZE = 20

export type RoleFilterValue = number | null

export interface AccountsLoadResult {
    count: number
    results: AccountApi[]
}

const EMPTY_RESULT: AccountsLoadResult = { count: 0, results: [] }

export const accountsLogic = kea<accountsLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        setTagsFilter: (tags: string[]) => ({ tags }),
        setAllRolesUnassigned: (value: boolean) => ({ value }),
        setCsmFilter: (value: RoleFilterValue) => ({ value }),
        setAccountExecutiveFilter: (value: RoleFilterValue) => ({ value }),
        setAccountOwnerFilter: (value: RoleFilterValue) => ({ value }),
        setCurrentPage: (page: number) => ({ page }),
        refresh: true,
    }),
    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        tagsFilter: [
            [] as string[],
            {
                setTagsFilter: (_, { tags }) => tags,
            },
        ],
        allRolesUnassigned: [
            false,
            {
                setAllRolesUnassigned: (_, { value }) => value,
            },
        ],
        csmFilter: [
            null as RoleFilterValue,
            {
                setCsmFilter: (_, { value }) => value,
            },
        ],
        accountExecutiveFilter: [
            null as RoleFilterValue,
            {
                setAccountExecutiveFilter: (_, { value }) => value,
            },
        ],
        accountOwnerFilter: [
            null as RoleFilterValue,
            {
                setAccountOwnerFilter: (_, { value }) => value,
            },
        ],
        currentPage: [
            1,
            {
                setCurrentPage: (_, { page }) => page,
            },
        ],
    }),
    loaders(({ values }) => ({
        accounts: [
            EMPTY_RESULT,
            {
                loadAccounts: async (_ = null, breakpoint) => {
                    await breakpoint(300)
                    const projectId = String(values.currentTeamId)
                    const params: Record<string, string | number | boolean> = {
                        limit: ACCOUNTS_PAGE_SIZE,
                        offset: (values.currentPage - 1) * ACCOUNTS_PAGE_SIZE,
                    }
                    if (values.searchQuery.trim()) {
                        params.search = values.searchQuery.trim()
                    }
                    if (values.tagsFilter.length > 0) {
                        params.tags = JSON.stringify(values.tagsFilter)
                    }
                    if (values.allRolesUnassigned) {
                        params.all_roles_unassigned = true
                    }
                    if (values.csmFilter !== null) {
                        params.csm = String(values.csmFilter)
                    }
                    if (values.accountExecutiveFilter !== null) {
                        params.account_executive = String(values.accountExecutiveFilter)
                    }
                    if (values.accountOwnerFilter !== null) {
                        params.account_owner = String(values.accountOwnerFilter)
                    }
                    try {
                        const response = await accountsList(projectId, params)
                        breakpoint()
                        return { count: response.count, results: response.results }
                    } catch (error) {
                        if (!isBreakpoint(error as Error)) {
                            posthog.captureException(error as Error, { scope: 'accountsLogic.loadAccounts' })
                            lemonToast.error('Failed to load accounts')
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    selectors({
        totalCount: [(s) => [s.accounts], (a: AccountsLoadResult): number => a.count],
        results: [(s) => [s.accounts], (a: AccountsLoadResult): AccountApi[] => a.results],
    }),
    listeners(({ actions, values }) => ({
        setSearchQuery: () => {
            actions.setCurrentPage(1)
        },
        setTagsFilter: () => {
            actions.setCurrentPage(1)
        },
        setAllRolesUnassigned: ({ value }) => {
            if (value) {
                if (values.csmFilter !== null) {
                    actions.setCsmFilter(null)
                }
                if (values.accountExecutiveFilter !== null) {
                    actions.setAccountExecutiveFilter(null)
                }
                if (values.accountOwnerFilter !== null) {
                    actions.setAccountOwnerFilter(null)
                }
            }
            actions.setCurrentPage(1)
        },
        setCsmFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
            actions.setCurrentPage(1)
        },
        setAccountExecutiveFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
            actions.setCurrentPage(1)
        },
        setAccountOwnerFilter: ({ value }) => {
            if (value !== null && values.allRolesUnassigned) {
                actions.setAllRolesUnassigned(false)
            }
            actions.setCurrentPage(1)
        },
        setCurrentPage: () => {
            actions.loadAccounts()
        },
        refresh: () => {
            actions.loadAccounts()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAccounts()
    }),
])
