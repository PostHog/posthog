import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { LemonSelectOption, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ActivityScope, CommentType, InsightShortId } from '~/types'

import type { commentsLogicType } from './commentsLogicType'

export const SCOPE_OPTIONS: LemonSelectOption<ActivityScope | null>[] = Object.values(ActivityScope).map((scope) => ({
    value: scope,
    label: capitalizeFirstLetter(scope),
}))
SCOPE_OPTIONS.unshift({
    value: null,
    label: 'Any',
})

const openUrls: Partial<Record<ActivityScope, (c: CommentType) => string | null>> = {
    [ActivityScope.INSIGHT]: (c) =>
        c.item_context?.short_id ? urls.insightView(c.item_context?.short_id as InsightShortId) : null,
    // TODO we only support this in modal apparently, but we should be able to open these at the timestamp of the comment
    [ActivityScope.REPLAY]: (c) => (c.item_id ? urls.replaySingle(c.item_id as string) : null),
    [ActivityScope.RECORDING]: (c) => (c.item_id ? urls.replaySingle(c.item_id as string) : null),
    [ActivityScope.DASHBOARD]: (c) => (c.item_id ? urls.dashboard(c.item_id) : null),
    [ActivityScope.FEATURE_FLAG]: (c) => (c.item_id ? urls.featureFlag(c.item_id) : null),
    [ActivityScope.EXPERIMENT]: (c) => (c.item_id ? urls.experiment(c.item_id) : null),
    [ActivityScope.COHORT]: (c) => (c.item_id ? urls.cohort(c.item_id) : null),
    [ActivityScope.PERSON]: (c) => (c.item_id ? urls.personByUUID(c.item_id) : null),
    [ActivityScope.ACTION]: (c) => (c.item_id ? urls.action(c.item_id) : null),
    [ActivityScope.EVENT_DEFINITION]: (c) => (c.item_id ? urls.eventDefinition(c.item_id) : null),
    [ActivityScope.PROPERTY_DEFINITION]: (c) => (c.item_id ? urls.propertyDefinition(c.item_id) : null),
    [ActivityScope.NOTEBOOK]: (c) => (c.item_id ? urls.notebook(c.item_id) : null),
    [ActivityScope.SURVEY]: (c) => (c.item_id ? urls.survey(c.item_id) : null),
    [ActivityScope.EARLY_ACCESS_FEATURE]: (c) => (c.item_id ? urls.earlyAccessFeature(c.item_id) : null),
    [ActivityScope.ERROR_TRACKING_ISSUE]: (c) => (c.item_id ? urls.errorTrackingIssue(c.item_id) : null),
    [ActivityScope.USER_INTERVIEW]: (c) => (c.item_id ? urls.userInterview(c.item_id) : null),
    // These scopes don't have direct URLs or need special handling:
    [ActivityScope.GROUP]: (c) =>
        c.item_context?.group_type_index && c.item_id ? urls.group(c.item_context.group_type_index, c.item_id) : null,
    [ActivityScope.PLUGIN]: (c) => (c.item_id ? urls.legacyPlugin(c.item_id) : null),
    [ActivityScope.HOG_FUNCTION]: (c) => (c.item_id ? urls.hogFunction(c.item_id) : null),
    // These don't have specific item URLs:
    [ActivityScope.TEAM]: () => urls.settings('project'),
    [ActivityScope.DATA_MANAGEMENT]: () => urls.eventDefinitions(),
    [ActivityScope.DATA_WAREHOUSE_SAVED_QUERY]: () => urls.database(),
    // Not linkable:
    [ActivityScope.PLUGIN_CONFIG]: () => null,
    [ActivityScope.COMMENT]: () => null,
}

export const openURLFor = (c: CommentType): string | null => {
    const commentURLFn = openUrls[c.scope as ActivityScope]
    if (!commentURLFn) {
        return null
    }

    const commentURL = commentURLFn(c)
    if (c.scope === ActivityScope.RECORDING) {
        // individual recording comments don't use the discussion panel
        return commentURL
    }
    return commentURL ? `${commentURL}#panel=discussion` : null
}

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
                    await breakpoint(25)
                    await api.comments.delete(id)
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
        deleteCommentSuccess: () => {
            lemonToast.success('Comment deleted')
        },
        deleteCommentFailure: (e) => {
            posthog.captureException(e, { action: 'data management scene deleting comment' })
            lemonToast.error('Could not delete comment, refresh and try again')
        },
    })),
])
