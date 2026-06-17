import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { Sorting } from 'lib/lemon-ui/LemonTable'
import { objectsEqual } from 'lib/utils/objects'
import { pluralize } from 'lib/utils/strings'

import { ApiConfig } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { trackedActionToUrl } from '~/lib/logic/scenes/trackedActionToUrl'
import { urls } from '~/scenes/urls'

import {
    llmAnalyticsScoreDefinitionsList as aiObservabilityScoreDefinitionsList,
    llmAnalyticsScoreDefinitionsPartialUpdate as aiObservabilityScoreDefinitionsPartialUpdate,
} from '../generated/api'
import type {
    ExperimentMetricKindEnumApi as ScoreDefinitionKind,
    PaginatedScoreDefinitionListApi,
    ScoreDefinitionApi,
} from '../generated/api.schemas'
import type { aiObservabilityScoreDefinitionsLogicType } from './aiObservabilityScoreDefinitionsLogicType'
import { getApiErrorDetail, getCurrentProjectId, type ScoreDefinitionModalMode } from './scoreDefinitionModalUtils'

export const SCORE_DEFINITIONS_PER_PAGE = 30

export interface ScoreDefinitionFilters {
    page: number
    search: string
    kind: ScoreDefinitionKind | ''
    archived: '' | 'true' | 'false'
    order_by: string
}

type ScoreDefinitionFilterInput = Omit<Partial<ScoreDefinitionFilters>, 'archived'> & {
    archived?: ScoreDefinitionFilters['archived'] | 'all' | boolean | null
}

const ALLOWED_ORDER_BY_VALUES = new Set([
    'name',
    '-name',
    'kind',
    '-kind',
    'created_at',
    '-created_at',
    'updated_at',
    '-updated_at',
    'current_version',
    '-current_version',
])

function cleanFilters(values: ScoreDefinitionFilterInput): ScoreDefinitionFilters {
    const orderBy = values.order_by && ALLOWED_ORDER_BY_VALUES.has(values.order_by) ? values.order_by : 'name'

    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        kind:
            values.kind === 'categorical' || values.kind === 'numeric' || values.kind === 'boolean' ? values.kind : '',
        archived:
            values.archived === 'all' || values.archived === ''
                ? ''
                : values.archived === undefined || values.archived === null
                  ? 'false'
                  : values.archived === 'true' || values.archived === true
                    ? 'true'
                    : values.archived === 'false' || values.archived === false
                      ? 'false'
                      : 'false',
        order_by: orderBy,
    }
}

function getUrlFilters(filters: ScoreDefinitionFilters): Record<string, unknown> {
    return {
        page: filters.page === 1 ? undefined : filters.page,
        search: filters.search || undefined,
        kind: filters.kind || undefined,
        archived: filters.archived === 'false' ? undefined : filters.archived === '' ? 'all' : 'true',
        order_by: filters.order_by === 'name' ? undefined : filters.order_by,
    }
}

export type AIObservabilityScoreDefinitionsLogicProps = Record<string, never>

export const aiObservabilityScoreDefinitionsLogic = kea<aiObservabilityScoreDefinitionsLogicType>([
    path(['products', 'ai_observability', 'frontend', 'scoreDefinitions', 'aiObservabilityScoreDefinitionsLogic']),
    props({} as AIObservabilityScoreDefinitionsLogicProps),

    actions({
        setFilters: (filters: Partial<ScoreDefinitionFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadScoreDefinitions: (debounce: boolean = true) => ({ debounce }),
        openModal: (mode: ScoreDefinitionModalMode, scoreDefinition: ScoreDefinitionApi | null = null) => ({
            mode,
            scoreDefinition,
        }),
        closeModal: true,
        toggleArchive: (scoreDefinition: ScoreDefinitionApi) => ({ scoreDefinition }),
        toggleArchiveSuccess: (definitionId: string) => ({ definitionId }),
        toggleArchiveFailure: (definitionId: string) => ({ definitionId }),
    }),

    reducers({
        rawFilters: [
            null as Partial<ScoreDefinitionFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
        modalMode: [
            null as ScoreDefinitionModalMode | null,
            {
                openModal: (_, { mode }) => mode,
                closeModal: () => null,
            },
        ],
        selectedDefinition: [
            null as ScoreDefinitionApi | null,
            {
                openModal: (_, { scoreDefinition }) => scoreDefinition,
                closeModal: () => null,
            },
        ],
        archivingDefinitionIds: [
            new Set<string>(),
            {
                toggleArchive: (state, { scoreDefinition }) => {
                    const nextState = new Set(state)
                    nextState.add(scoreDefinition.id)
                    return nextState
                },
                toggleArchiveSuccess: (state, { definitionId }) => {
                    const nextState = new Set(state)
                    nextState.delete(definitionId)
                    return nextState
                },
                toggleArchiveFailure: (state, { definitionId }) => {
                    const nextState = new Set(state)
                    nextState.delete(definitionId)
                    return nextState
                },
            },
        ],
    }),

    loaders(({ values }) => ({
        scoreDefinitions: [
            { results: [], count: 0, next: null, previous: null } as PaginatedScoreDefinitionListApi,
            {
                loadScoreDefinitions: async ({ debounce }, breakpoint) => {
                    if (debounce && values.scoreDefinitions.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values

                    return aiObservabilityScoreDefinitionsList(String(ApiConfig.getCurrentTeamId()), {
                        search: filters.search || undefined,
                        kind: filters.kind || undefined,
                        archived: filters.archived === '' ? undefined : filters.archived === 'true' ? true : false,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * SCORE_DEFINITIONS_PER_PAGE),
                        limit: SCORE_DEFINITIONS_PER_PAGE,
                    })
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<ScoreDefinitionFilters> | null): ScoreDefinitionFilters =>
                cleanFilters(rawFilters || {}),
        ],

        count: [
            (s) => [s.scoreDefinitions],
            (scoreDefinitions: PaginatedScoreDefinitionListApi) => scoreDefinitions.count,
        ],

        sorting: [
            (s) => [s.filters],
            (filters: ScoreDefinitionFilters): Sorting | null => {
                if (!filters.order_by) {
                    return {
                        columnKey: 'name',
                        order: 1,
                    }
                }

                return filters.order_by.startsWith('-')
                    ? {
                          columnKey: filters.order_by.slice(1),
                          order: -1,
                      }
                    : {
                          columnKey: filters.order_by,
                          order: 1,
                      }
            },
        ],

        pagination: [
            (s) => [s.filters, s.count],
            (filters: ScoreDefinitionFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: SCORE_DEFINITIONS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        scoreDefinitionCountLabel: [
            (s) => [s.filters, s.count, s.scoreDefinitionsLoading],
            (filters: ScoreDefinitionFilters, count: number, loading: boolean): string => {
                if (loading) {
                    return ''
                }

                const start = (filters.page - 1) * SCORE_DEFINITIONS_PER_PAGE + 1
                const end = Math.min(filters.page * SCORE_DEFINITIONS_PER_PAGE, count)

                return count === 0 ? '0 scorers' : `${start}-${end} of ${pluralize(count, 'scorer')}`
            },
        ],
        isArchivingDefinition: [
            (s) => [s.archivingDefinitionIds],
            (archivingDefinitionIds): ((definitionId: string) => boolean) => {
                return (definitionId: string) => archivingDefinitionIds.has(definitionId)
            },
        ],
    }),

    listeners(({ actions, asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)

            if (!objectsEqual(oldFilters, values.filters)) {
                await asyncActions.loadScoreDefinitions(debounce)
            }
        },

        toggleArchive: async ({ scoreDefinition }) => {
            try {
                await aiObservabilityScoreDefinitionsPartialUpdate(getCurrentProjectId(), scoreDefinition.id, {
                    archived: !scoreDefinition.archived,
                })
                actions.toggleArchiveSuccess(scoreDefinition.id)
                lemonToast.success(scoreDefinition.archived ? 'Scorer unarchived.' : 'Scorer archived.')
                await asyncActions.loadScoreDefinitions(false)
            } catch (error) {
                actions.toggleArchiveFailure(scoreDefinition.id)
                lemonToast.error(getApiErrorDetail(error) || 'Failed to update scorer state.')
            }
        },
    })),

    trackedActionToUrl(({ values }) => ({
        setFilters: () => {
            const nextValues = { ...getUrlFilters(values.filters), human_reviews_tab: 'scorers' }
            const urlValues = {
                ...getUrlFilters(cleanFilters(router.values.searchParams)),
                human_reviews_tab: router.values.searchParams.human_reviews_tab === 'scorers' ? 'scorers' : undefined,
            }

            if (!objectsEqual(nextValues, urlValues)) {
                // This logic owns the bare params (search, page, ...) — pass everyone
                // else's through (review_*, queue_*, shared filters) instead of stripping them.
                return [
                    urls.aiObservabilityReviews(),
                    { ...router.values.searchParams, ...nextValues },
                    {},
                    { replace: true },
                ]
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.aiObservabilityReviews()]: (_, searchParams, __, { method }) => {
            const newFilters = cleanFilters(searchParams)

            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            } else if (method !== 'REPLACE') {
                actions.loadScoreDefinitions(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadScoreDefinitions()
    }),
])
