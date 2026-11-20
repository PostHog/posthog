import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo } from 'react'

import api, { PaginatedResponse } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { LoadTags, TagOption, excludingTags, tagSelectLogic } from './tagSelectLogic'

const TAGS_PER_PAGE = 100

export function useTagSource(options?: TagOption[], customLoadTags?: LoadTags): LoadTags {
    const { currentTeamId } = useValues(teamLogic)
    return useCallback<LoadTags>(
        async (query, offset, isStale) => {
            if (options) {
                const matches = options.filter((option) => option.tag.toLowerCase().includes(query.toLowerCase()))
                return {
                    results: matches.slice(offset, offset + TAGS_PER_PAGE),
                    hasMore: offset + TAGS_PER_PAGE < matches.length,
                }
            }
            if (customLoadTags) {
                return customLoadTags(query, offset, isStale)
            }
            if (currentTeamId == null) {
                return { results: [], hasMore: false }
            }
            const params = new URLSearchParams({ search: query, limit: String(TAGS_PER_PAGE), offset: String(offset) })
            // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. No generated function covers this endpoint yet. Find out why the generated client skips it (no schema, no product tag, or excluded from the spec) and fix that first.
            const page: PaginatedResponse<string> = await api.get(`api/projects/${currentTeamId}/tags?${params}`)
            return {
                results: page.results.map((tag) => ({ tag })),
                hasMore: page.next != null,
                nextOffset: offset + page.results.length,
            }
        },
        [options, customLoadTags, currentTeamId]
    )
}

/** `exclude` must be defined outside the component, because a new function on each render starts a new search. */
export function useTagSourceExcluding(exclude: (tag: string) => boolean): LoadTags {
    const projectTags = useTagSource()
    return useMemo(() => excludingTags(projectTags, exclude), [projectTags, exclude])
}

export interface TagPages {
    tags: TagOption[]
    search: string
    open: boolean
    awaitingFirstPage: boolean
    pageLoading: boolean
    error: string | null
    setOpen: (open: boolean) => void
    setSearch: (search: string) => void
    loadMore: () => void
    retry: () => void
}

export function useTagPages(logicKey: string, loadTags?: LoadTags): TagPages {
    const logic = tagSelectLogic({ logicKey })
    const {
        awaitingFirstPage,
        nextOffset,
        requestEpoch,
        search,
        showPopover,
        tagPageError,
        tagPageLoading,
        tagResults,
    } = useValues(logic)
    const { loadMoreTags, loadTagPage, setSearch, setShowPopover } = useActions(logic)
    const projectSource = useTagSource()
    const source = loadTags ?? projectSource

    useEffect(() => {
        if (showPopover) {
            loadTagPage({ search, offset: 0, loadTags: source, requestEpoch })
        }
    }, [showPopover, search, source, loadTagPage, requestEpoch])

    return {
        tags: tagResults,
        search,
        open: showPopover,
        awaitingFirstPage,
        pageLoading: tagPageLoading,
        error: tagPageError,
        // LemonInputSelect refocuses after every pick. A repeat open would reset the paging state without loading a page.
        setOpen: (next) => {
            if (next !== showPopover) {
                setShowPopover(next)
            }
        },
        // Some inputs report a cleared search as they close, which would leave the next open waiting for a page nobody asked for.
        // Typing into a closed input reports the text before the open, so a non-empty search opens it.
        setSearch: (next) => {
            if (!showPopover && !next) {
                return
            }
            if (!showPopover) {
                setShowPopover(true)
            }
            setSearch(next)
        },
        loadMore: () => loadMoreTags(source),
        retry: () => loadTagPage({ search, offset: nextOffset, loadTags: source, requestEpoch }),
    }
}
