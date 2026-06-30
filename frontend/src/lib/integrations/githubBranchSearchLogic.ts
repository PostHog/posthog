import { actions, afterMount, isBreakpoint, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import type { githubBranchSearchLogicType } from './githubBranchSearchLogicType'

const PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 300

export interface GithubBranchSearchLogicProps {
    integrationId: number
    /** Repository in `owner/repo` format whose branches to list. */
    repo: string
}

/**
 * Server-side searchable, paginated GitHub branch source for a single repository. Mirrors
 * {@link githubRepositorySearchLogic} but for the `github_branches` endpoint (which is repo-scoped), and
 * additionally captures the repository's default branch so a picker can pre-select it. Keyed by integration
 * id + repo so each repository's branch list stays independent.
 */
export const githubBranchSearchLogic = kea<githubBranchSearchLogicType>([
    props({} as GithubBranchSearchLogicProps),
    key((props) => `${props.integrationId}:${props.repo}`),
    path((key) => ['lib', 'integrations', 'githubBranchSearchLogic', key]),

    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        loadPage: (offset: number) => ({ offset }),
        loadPageSuccess: (branches: string[], defaultBranch: string | null, hasMore: boolean, offset: number) => ({
            branches,
            defaultBranch,
            hasMore,
            offset,
        }),
        loadPageFailure: true,
        loadMore: true,
        refresh: true,
    }),

    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        branches: [
            [] as string[],
            {
                setSearchQuery: () => [],
                refresh: () => [],
                loadPageSuccess: (state, { branches, offset }) => {
                    if (offset === 0) {
                        return branches
                    }
                    const seen = new Set(state)
                    return [...state, ...branches.filter((b) => !seen.has(b))]
                },
            },
        ],
        // The repo's default branch, surfaced by the endpoint; used by the picker for pre-selection.
        defaultBranch: [
            null as string | null,
            {
                loadPageSuccess: (state, { defaultBranch }) => defaultBranch ?? state,
            },
        ],
        loading: [
            false,
            {
                setSearchQuery: () => true,
                refresh: () => true,
                loadPage: () => true,
                loadPageSuccess: () => false,
                loadPageFailure: () => false,
            },
        ],
        hasMore: [
            false,
            {
                loadPageSuccess: (_, { hasMore }) => hasMore,
                loadPageFailure: () => false,
            },
        ],
        currentOffset: [
            0,
            {
                setSearchQuery: () => 0,
                refresh: () => 0,
                loadPageSuccess: (_, { offset }) => offset + PAGE_SIZE,
            },
        ],
    }),

    listeners(({ actions, values, props }) => ({
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            actions.loadPage(0)
        },
        refresh: () => {
            actions.loadPage(0)
        },
        loadMore: () => {
            if (values.hasMore && !values.loading) {
                actions.loadPage(values.currentOffset)
            }
        },
        loadPage: async ({ offset }, breakpoint) => {
            try {
                const response = await api.integrations.githubBranches(props.integrationId, {
                    repo: props.repo,
                    limit: PAGE_SIZE,
                    offset,
                    search: values.searchQuery.trim() || undefined,
                })
                await breakpoint()
                actions.loadPageSuccess(response.branches, response.default_branch ?? null, response.has_more, offset)
            } catch (e: any) {
                if (isBreakpoint(e)) {
                    throw e
                }
                actions.loadPageFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPage(0)
    }),
])
