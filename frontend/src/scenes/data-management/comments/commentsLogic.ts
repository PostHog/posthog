import { LemonSelectOption, lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ActivityScope, CommentType } from '~/types'

import type { commentsLogicType } from './commentsLogicType'
import { capitalizeFirstLetter } from 'lib/utils'
import posthog from 'posthog-js'

export const SCOPE_OPTIONS: LemonSelectOption<ActivityScope | null>[] = Object.values(ActivityScope).map((scope) => ({
    value: scope,
    label: capitalizeFirstLetter(scope),
}))
SCOPE_OPTIONS.unshift({
    value: null,
    label: 'Any',
})

export const commentsLogic = kea<commentsLogicType>([
    path(['scenes', 'data-management', 'comments', 'commentsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], userLogic, ['user']],
    })),
    actions({
        setScope: (scope: ActivityScope | null) => ({ scope }),
        setFilterCreatedBy: (createdBy: string | null) => ({ createdBy }),
        setSearchText: (searchText: string) => ({ searchText }),
        deleteComment: (id: string) => ({ id }),
        loadComments: true,
    }),
    loaders(({ values }) => ({
        comments: [
            [] as CommentType[],
            {
                loadComments: async (_, breakpoint) => {
                    await breakpoint(100)
                    const params: Record<string, any> = {}

                    if (values.scope) {
                        params.scope = values.scope
                    }

                    if (values.filterCreatedBy) {
                        params.created_by = values.filterCreatedBy
                    }

                    if (values.searchText.trim()) {
                        params.search = values.searchText.trim()
                    }

                    const response = await api.comments.list(params)
                    breakpoint()
                    return response.results || []
                },
                deleteComment: async ({ id }: { id: CommentType['id'] }, breakpoint) => {
                    try {
                        await breakpoint(25)
                        await api.comments.update(id, { deleted: true })
                    } catch (e) {
                        posthog.captureException(e)
                        lemonToast.error('Could not delete comment')
                    }
                    return values.comments.filter((c) => c.id !== id)
                },
            },
        ],
    })),
    reducers(() => ({
        scope: [null as ActivityScope | null, { setScope: (_, { scope }) => scope }],
        filterCreatedBy: [null as string | null, { setFilterCreatedBy: (_, { createdBy }) => createdBy }],
        searchText: ['', { setSearchText: (_, { searchText }) => searchText }],
    })),
    selectors(() => ({
        hasAnySearch: [
            (s) => [s.searchText, s.scope, s.filterCreatedBy],
            (searchText, scope, filterCreatedBy) => {
                return !!searchText || !!scope || !!filterCreatedBy
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.comments, s.commentsLoading, s.hasAnySearch],
            (comments, commentsLoading, hasAnySearch): boolean => {
                return comments.length === 0 && !commentsLoading && !hasAnySearch
            },
        ],
    })),
    listeners(({ actions }) => ({
        setScope: actions.loadComments,
        setFilterCreatedBy: actions.loadComments,
        setSearchText: actions.loadComments,
    })),
])
