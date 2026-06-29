import { actions, afterMount, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import type { githubRepositorySearchLogicType } from './githubRepositorySearchLogicType'

const PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 300

export interface GithubRepositorySearchLogicProps {
    id: number
}

/**
 * Server-side searchable, paginated GitHub repository source for a single integration. Unlike
 * {@link githubIntegrationLogic} — which eagerly bulk-loads every repository in 500-row pages and ignores
 * the search term — this drives the `github_repos` endpoint's `search`/`limit`/`offset` params directly so
 * a repo picker can search across very large accounts without loading the whole list. Keyed by integration
 * id so concurrent pickers stay independent.
 */
export const githubRepositorySearchLogic = kea<githubRepositorySearchLogicType>([
    props({} as GithubRepositorySearchLogicProps),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'githubRepositorySearchLogic', key]),

    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        loadPage: (offset: number) => ({ offset }),
        loadPageSuccess: (repositories: GitHubRepoApi[], hasMore: boolean, offset: number) => ({
            repositories,
            hasMore,
            offset,
        }),
        loadPageFailure: (error: string) => ({ error }),
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
        repositories: [
            [] as GitHubRepoApi[],
            {
                // A new query or refresh starts a fresh list; the first page (offset 0) replaces, later pages
                // append (deduped by id) so "Load more" extends the current result set.
                setSearchQuery: () => [],
                refresh: () => [],
                loadPageSuccess: (state, { repositories, offset }) => {
                    if (offset === 0) {
                        return repositories
                    }
                    const seenIds = new Set(state.map((r) => r.id))
                    return [...state, ...repositories.filter((r: GitHubRepoApi) => !seenIds.has(r.id))]
                },
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
        error: [
            null as string | null,
            {
                setSearchQuery: () => null,
                refresh: () => null,
                loadPage: () => null,
                loadPageSuccess: () => null,
                loadPageFailure: (_, { error }) => error,
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

    selectors({
        // The picker selects on `owner/repo` (matches the Task API's repository format).
        repositoryNames: [
            (s) => [s.repositories],
            (repositories: GitHubRepoApi[]): string[] => repositories.map((r) => r.full_name),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        // Debounce keystrokes so a multi-character search fires one request, not one per character.
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
            // Snapshot the query driving this request so a response that resolves after the search
            // has moved on (e.g. a slow "Load more" landing mid-typing) can be discarded instead of
            // committing stale repositories onto the new result set.
            const query = values.searchQuery.trim()
            try {
                const response = await api.integrations.githubRepositories(props.id, {
                    limit: PAGE_SIZE,
                    offset,
                    search: query || undefined,
                })
                await breakpoint()
                if (query !== values.searchQuery.trim()) {
                    return
                }
                actions.loadPageSuccess(response.repositories, response.has_more, offset)
            } catch (e: any) {
                if (isBreakpoint(e)) {
                    throw e
                }
                actions.loadPageFailure(e?.detail || e?.message || 'Failed to load repositories.')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPage(0)
    }),
])
