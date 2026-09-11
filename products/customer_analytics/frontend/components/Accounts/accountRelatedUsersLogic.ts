import {
    MakeLogicType,
    actions,
    afterMount,
    isBreakpoint,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { Sorting } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { OrganizationMemberType, Region } from '~/types'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { AccountsEvents } from './constants'

export type AccountOrganizationMember = Pick<OrganizationMemberType, 'id' | 'user' | 'level' | 'last_login'> & {
    region: Region.US | Region.EU
}

export const PAGE_SIZE = 20

// EU-region orgs have no rows in this region's posthog_user tables; eu_org_members is a
// materialized DWH pre-join of the EU postgres sync (prod-only, refreshed daily).
const EU_MEMBERS_VIEW = 'eu_org_members'
const EU_MEMBERS_LIMIT = 3000

const isExpectedMissingViewError = (error: unknown): boolean => {
    const message = error instanceof Error ? error.message : String(error ?? '')
    return (
        message.includes(EU_MEMBERS_VIEW) &&
        (message.includes("don't have access to table") || message.includes('Unknown table'))
    )
}

/** Column keys the table can sort by. They double as the backend's whitelisted `ordering` values. */
export type RelatedUsersSortKey = 'level' | 'last_login'

export interface RelatedUsersQuery {
    searchTerm: string
    levels: OrganizationMembershipLevel[]
    sorting: Sorting | null
}

// Maps the table's sorting state onto the backend's whitelisted `ordering` param.
const sortingToOrdering = (sorting: Sorting | null): string | undefined => {
    if (!sorting) {
        return undefined
    }
    return sorting.order === -1 ? `-${sorting.columnKey}` : sorting.columnKey
}

const memberMatchesSearch = (member: AccountOrganizationMember, searchTerm: string): boolean => {
    const normalizedSearch = searchTerm.trim().toLowerCase()
    if (!normalizedSearch) {
        return true
    }
    const { first_name, last_name, email } = member.user
    return `${first_name} ${last_name} ${email}`.toLowerCase().includes(normalizedSearch)
}

const compareMembers = (a: AccountOrganizationMember, b: AccountOrganizationMember, sorting: Sorting): number => {
    if (sorting.columnKey === 'level') {
        return (a.level - b.level) * sorting.order
    }
    if (sorting.columnKey === 'last_login') {
        if (!a.last_login || !b.last_login) {
            return a.last_login === b.last_login ? 0 : (a.last_login ? 1 : -1) * sorting.order
        }
        return a.last_login.localeCompare(b.last_login) * sorting.order
    }
    return 0
}

const paginateMembers = (
    members: AccountOrganizationMember[],
    page: number,
    { searchTerm, levels, sorting }: RelatedUsersQuery
): CountedPaginatedResponse<AccountOrganizationMember> => {
    const matchingMembers = members.filter(
        (member) => memberMatchesSearch(member, searchTerm) && (!levels.length || levels.includes(member.level))
    )
    const sortedMembers = sorting ? [...matchingMembers].sort((a, b) => compareMembers(a, b, sorting)) : matchingMembers
    return {
        results: sortedMembers.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
        count: sortedMembers.length,
    }
}

const fetchEuMembers = async (externalId: string): Promise<AccountOrganizationMember[] | null> => {
    try {
        const response = (await api.query({
            kind: NodeKind.HogQLQuery,
            tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
            query: hogql`
                select user_id, membership_id, level, first_name, last_name, email, distinct_id, last_login
                from eu_org_members
                where organization_id = ${externalId}
                order by joined_at desc
                limit ${EU_MEMBERS_LIMIT}
            `,
        })) as HogQLQueryResponse
        const rows = (response.results ?? []) as unknown[][]
        return rows.map((row) => ({
            id: String(row[1]),
            level: Number(row[2]) as AccountOrganizationMember['level'],
            user: {
                id: Number(row[0]),
                first_name: (row[3] as string | null) ?? '',
                last_name: (row[4] as string | null) ?? '',
                email: (row[5] as string | null) ?? '',
                distinct_id: (row[6] as string | null) ?? '',
            } as AccountOrganizationMember['user'],
            last_login: (row[7] as string | null) ?? null,
            region: Region.EU,
        }))
    } catch (error) {
        if (!isExpectedMissingViewError(error)) {
            posthog.captureException(error as Error, {
                scope: 'accountRelatedUsersLogic.fetchEuMembers',
            })
        }
        return null
    }
}

export interface AccountRelatedUsersLogicProps {
    externalId: string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountRelatedUsersLogicValues {
    levels: OrganizationMembershipLevel[]
    membersResponse: CountedPaginatedResponse<AccountOrganizationMember> | null
    membersResponseLoading: boolean
    page: number
    query: RelatedUsersQuery
    searchTerm: string
    sorting: Sorting | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountRelatedUsersLogicActions {
    loadMembers: (_?: any) => any
    loadMembersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMembersSuccess: (
        membersResponse: CountedPaginatedResponse<AccountOrganizationMember>,
        payload?: any
    ) => {
        membersResponse: CountedPaginatedResponse<AccountOrganizationMember>
        payload?: any
    }
    setLevels: (levels: OrganizationMembershipLevel[]) => {
        levels: OrganizationMembershipLevel[]
    }
    setPage: (page: number) => {
        page: number
    }
    setSearchTerm: (searchTerm: string) => {
        searchTerm: string
    }
    setSorting: (sorting: Sorting | null) => {
        sorting: Sorting | null
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountRelatedUsersLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        query: (searchTerm: string, levels: OrganizationMembershipLevel[], sorting: Sorting | null) => RelatedUsersQuery
    }
}

export type accountRelatedUsersLogicType = MakeLogicType<
    accountRelatedUsersLogicValues,
    accountRelatedUsersLogicActions,
    AccountRelatedUsersLogicProps,
    accountRelatedUsersLogicMeta
>

export const accountRelatedUsersLogic = kea<accountRelatedUsersLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountRelatedUsersLogic', key]),
    props({} as AccountRelatedUsersLogicProps),
    // Accounts with no external_id all share the empty-string key, which is benign: afterMount skips loading when externalId is falsy.
    key((props) => props.externalId),
    actions({
        setPage: (page: number) => ({ page }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setLevels: (levels: OrganizationMembershipLevel[]) => ({ levels }),
        setSorting: (sorting: Sorting | null) => ({ sorting }),
    }),
    reducers({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setSearchTerm: () => 1,
                setLevels: () => 1,
                setSorting: () => 1,
            },
        ],
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        levels: [[] as OrganizationMembershipLevel[], { setLevels: (_, { levels }) => levels }],
        sorting: [null as Sorting | null, { setSorting: (_, { sorting }) => sorting }],
    }),
    selectors({
        query: [
            (s) => [s.searchTerm, s.levels, s.sorting],
            (
                searchTerm: string,
                levels: OrganizationMembershipLevel[],
                sorting: Sorting | null
            ): RelatedUsersQuery => ({ searchTerm, levels, sorting }),
        ],
    }),
    loaders(({ cache, props, values }) => ({
        membersResponse: [
            null as CountedPaginatedResponse<AccountOrganizationMember> | null,
            {
                loadMembers: async (_ = null, breakpoint) => {
                    if (cache.euMembers) {
                        return paginateMembers(cache.euMembers, values.page, values.query)
                    }
                    try {
                        const search = values.searchTerm.trim()
                        const levels = values.levels.join(',')
                        const response = await api.organizationMembers.listForOrg(props.externalId, {
                            limit: PAGE_SIZE,
                            offset: (values.page - 1) * PAGE_SIZE,
                            ...(search ? { search } : {}),
                            ...(levels ? { levels } : {}),
                            ...(values.sorting ? { ordering: sortingToOrdering(values.sorting) } : {}),
                        })
                        breakpoint()
                        if (response.count > 0) {
                            cache.isUsOrg = true
                            return {
                                ...response,
                                results: response.results.map((member) => ({ ...member, region: Region.US })),
                            }
                        }
                        if (!cache.isUsOrg) {
                            const euMembers = await fetchEuMembers(props.externalId)
                            breakpoint()
                            if (euMembers?.length) {
                                cache.euMembers = euMembers
                                return paginateMembers(euMembers, values.page, values.query)
                            }
                        }
                        return { ...response, results: [] }
                    } catch (error) {
                        if (!isBreakpoint(error as Error)) {
                            posthog.captureException(error as Error, {
                                scope: 'accountRelatedUsersLogic.loadMembers',
                            })
                            lemonToast.error('Failed to load related users')
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        setPage: () => actions.loadMembers(),
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            await breakpoint(300)
            actions.loadMembers()
            posthog.capture(AccountsEvents.RelatedUsersSearched, {
                has_query: searchTerm.trim().length > 0,
                query_length: searchTerm.trim().length,
            })
        },
        setLevels: ({ levels }) => {
            actions.loadMembers()
            posthog.capture(AccountsEvents.RelatedUsersFiltered, { levels })
        },
        setSorting: ({ sorting }) => {
            actions.loadMembers()
            posthog.capture(AccountsEvents.RelatedUsersSorted, {
                column: (sorting?.columnKey as RelatedUsersSortKey | undefined) ?? null,
                direction: sorting ? (sorting.order === -1 ? 'desc' : 'asc') : 'cleared',
            })
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.externalId) {
            actions.loadMembers()
        }
    }),
])
