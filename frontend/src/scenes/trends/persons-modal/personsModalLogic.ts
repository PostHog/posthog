import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { isGroupType } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import {
    ActorsQuery,
    DataTableNode,
    FunnelCorrelationActorsQuery,
    FunnelsActorsQuery,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    InsightActorsQueryOptionsResponse,
    insightActorsQueryOptionsResponseKeys,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ActorType,
    BreakdownType,
    ChartDisplayType,
    CommonActorType,
    GroupActorType,
    IntervalType,
    PersonActorType,
    PropertiesTimelineFilterType,
} from '~/types'

import type { personsModalLogicType } from './personsModalLogicType'

const RESULTS_PER_PAGE = 100

export interface PersonModalLogicProps {
    query?: InsightActorsQuery | FunnelsActorsQuery | FunnelCorrelationActorsQuery | null
    url?: string | null
    additionalSelect?: Partial<Record<keyof CommonActorType, string>>
    orderBy?: string[]
}

export interface ListActorsResponse {
    results: {
        count: number
        people: ActorType[]
    }[]
    missing_persons?: number
    next?: string
    offset?: number // Offset for HogQL queries
}

export const personsModalLogic = kea<personsModalLogicType>([
    path(['scenes', 'trends', 'personsModalLogic']),
    props({} as PersonModalLogicProps),
    actions({
        setSearchTerm: (search: string) => ({ search }),
        saveAsCohort: (cohortName: string) => ({ cohortName }),
        resetActors: () => true,
        closeModal: () => true,
        setIsCohortModalOpen: (isOpen: boolean) => ({ isOpen }),
        loadActors: ({ url, clear, offset }: { url?: string | null; clear?: boolean; offset?: number }) => ({
            url,
            clear,
            offset,
        }),
        loadNextActors: true,
        updateQuery: (query: InsightActorsQuery) => ({ query }),
        updateActorsQuery: (query: Partial<InsightActorsQuery>) => ({ query }),
        loadActorsQueryOptions: (query: InsightActorsQuery) => ({ query }),
    }),
    connect(() => ({
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
        actions: [eventUsageLogic, ['reportPersonsModalViewed']],
    })),

    loaders(({ values, actions, props }) => ({
        actorsResponse: [
            null as ListActorsResponse | null,
            {
                loadActors: async ({ url, clear, offset }, breakpoint) => {
                    if (url) {
                        url += '&include_recordings=true'

                        if (values.searchTerm) {
                            url += `&search=${values.searchTerm}`
                        }
                    }
                    if (url && !values.actorsQuery) {
                        const res = await api.get(url)
                        breakpoint()

                        if (clear) {
                            actions.resetActors()
                        }
                        return res
                    }
                    if (values.actorsQuery) {
                        const response = await performQuery(
                            setLatestVersionsOnQuery(
                                {
                                    ...values.actorsQuery,
                                    limit: offset ? offset * 2 : RESULTS_PER_PAGE,
                                    offset,
                                },
                                { recursion: false }
                            ) as ActorsQuery
                        )
                        breakpoint()

                        const assembledSelectFields = values.selectFields
                        const additionalFieldIndices = Object.values(props.additionalSelect || {}).map((field) =>
                            assembledSelectFields.indexOf(field)
                        )
                        const newResponse: ListActorsResponse = {
                            results: [
                                {
                                    count: response.results.length,
                                    people: response.results.map((result): ActorType => {
                                        if (result[0].group_type_index !== undefined) {
                                            const group: GroupActorType = {
                                                type: 'group',
                                                id: result[0].id,
                                                group_key: result[0].group_key,
                                                group_type_index: result[0].group_type_index,
                                                properties: result[0].group_properties,
                                                created_at: result[0].created_at,
                                                matched_recordings: [],
                                                value_at_data_point: null,
                                            }
                                            Object.keys(props.additionalSelect || {}).forEach((field, index) => {
                                                group[field] = result[additionalFieldIndices[index]]
                                            })
                                            return group
                                        }
                                        const person: PersonActorType = {
                                            type: 'person',
                                            id: result[0].id,
                                            distinct_ids: result[0].distinct_ids,
                                            is_identified: result[0].is_identified,
                                            properties: result[0].properties,
                                            created_at: result[0].created_at,
                                            matched_recordings: [],
                                            value_at_data_point: null,
                                        }

                                        Object.keys(props.additionalSelect || {}).forEach((field, index) => {
                                            person[field] = result[additionalFieldIndices[index]]
                                        })

                                        return person
                                    }),
                                },
                            ],
                        }
                        newResponse.offset = response.hasMore ? response.offset + response.limit : undefined
                        newResponse.missing_persons = response.missing_actors_count
                        if (clear) {
                            actions.resetActors()
                        }
                        return newResponse
                    }
                    return null
                },
            },
        ],
        insightActorsQueryOptions: [
            null as InsightActorsQueryOptionsResponse | null,
            {
                loadActorsQueryOptions: async ({ query }) => {
                    if (!query) {
                        return values.insightActorsQueryOptions || null
                    }
                    const optionsQuery: InsightActorsQueryOptions = setLatestVersionsOnQuery(
                        {
                            kind: NodeKind.InsightActorsQueryOptions,
                            source: query,
                        },
                        { recursion: false }
                    )
                    const response = await performQuery(optionsQuery, {}, 'blocking')

                    return Object.fromEntries(
                        Object.entries(response).filter(([key, _]) =>
                            insightActorsQueryOptionsResponseKeys.includes(key)
                        )
                    )
                },
            },
        ],
    })),

    reducers(({ props }) => ({
        query: [
            props.query as InsightActorsQuery | null,
            {
                updateQuery: (_, { query }) => query,
            },
        ],
        actors: [
            [] as ActorType[],
            {
                loadActorsSuccess: (state, { actorsResponse }) => [
                    ...state,
                    ...(actorsResponse?.results?.[0]?.people || []),
                ],
                resetActors: () => [],
            },
        ],
        errorObject: [
            null as Record<string, any> | null,
            {
                loadActors: () => null,
                loadActorsFailure: (_, { errorObject }) => errorObject,
                loadActorsSuccess: () => null,
            },
        ],
        missingActorsCount: [
            0,
            {
                loadActorsSuccess: (state, { actorsResponse }) => state + (actorsResponse?.missing_persons || 0),
                resetActors: () => 0,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { search }) => search,
            },
        ],
        isModalOpen: [
            true,
            {
                closeModal: () => false,
            },
        ],
        isCohortModalOpen: [
            false,
            {
                setIsCohortModalOpen: (_, { isOpen }) => isOpen,
                closeModal: () => false,
            },
        ],
    })),

    listeners(({ actions, values, props }) => ({
        setSearchTerm: async (_, breakpoint) => {
            await breakpoint(500)
            actions.loadActors({ url: props.url, clear: true })
        },
        saveAsCohort: async ({ cohortName }) => {
            const cohortParams = {
                is_static: true,
                name: cohortName,
            }
            const cohort = await api.create('api/cohort', { ...cohortParams, query: values.actorsQuery })
            cohortsModel.actions.cohortCreated(cohort)
            lemonToast.success('Cohort saved', {
                toastId: `cohort-saved-${cohort.id}`,
                button: {
                    label: 'View cohort',
                    action: () => router.actions.push(urls.cohort(cohort.id)),
                },
            })
            actions.setIsCohortModalOpen(false)
        },
        loadNextActors: () => {
            if (values.actorsResponse?.next) {
                actions.loadActors({ url: values.actorsResponse.next })
            }
            if (values.actorsResponse?.offset) {
                actions.loadActors({ offset: values.actorsResponse.offset })
            }
        },
        loadActors: () => {
            if (values.query && !values.insightActorsQueryOptions) {
                actions.loadActorsQueryOptions(values.query)
            }
        },
        updateActorsQuery: ({ query: q }) => {
            if (q && values.query) {
                actions.updateQuery({ ...values.query, ...q })
                actions.loadActors({ offset: 0, clear: true })
            }
        },
    })),

    selectors({
        actorLabel: [
            (s) => [s.actors, s.aggregationLabel],
            (actors, aggregationLabel) => {
                const firstResult = actors[0]

                if (!firstResult) {
                    return { singular: 'result', plural: 'results' }
                }
                return aggregationLabel(isGroupType(firstResult) ? firstResult.group_type_index : undefined)
            },
        ],
        validationError: [
            (s) => [s.errorObject],
            (errorObject): string | null => {
                // We use 512 for query timeouts
                return errorObject?.status === 400 || errorObject?.status === 512 ? errorObject.detail : null
            },
        ],
        propertiesTimelineFilterFromUrl: [
            () => [(_, p) => p.url],
            (url): PropertiesTimelineFilterType => {
                // PersonsModal only gets an persons URL and not its underlying filters, so we need to extract those
                const params = new URLSearchParams(url.split('?')[1])
                const eventsString = params.get('events')
                const actionsString = params.get('actions')
                const propertiesString = params.get('properties')
                const aggregationGroupTypeIndexString = params.get('aggregation_group_type_index')
                const filter: PropertiesTimelineFilterType = {
                    date_from: params.get('date_from') || undefined,
                    date_to: params.get('date_to') || undefined,
                    interval: (params.get('interval') || undefined) as IntervalType | undefined,
                    events: eventsString ? JSON.parse(eventsString) : undefined,
                    actions: actionsString ? JSON.parse(actionsString) : undefined,
                    properties: propertiesString ? JSON.parse(propertiesString) : undefined,
                    aggregation_group_type_index: aggregationGroupTypeIndexString
                        ? parseInt(aggregationGroupTypeIndexString)
                        : undefined,
                    display: (params.get('display') || undefined) as ChartDisplayType | undefined,
                    breakdown: params.get('breakdown') || undefined,
                    breakdown_type: (params.get('breakdown_type') || undefined) as BreakdownType | undefined,
                }
                return cleanFilters(filter)
            },
        ],
        selectFields: [
            () => [(_, p) => p.additionalSelect],
            (additionalSelect: PersonModalLogicProps['additionalSelect']): string[] => {
                const extra = Object.values(additionalSelect || {})
                return ['actor', ...extra]
            },
        ],
        actorsQuery: [
            (s) => [(_, p) => p.orderBy, s.query, s.searchTerm, s.selectFields],
            (orderBy, query, searchTerm, selectFields): ActorsQuery | null => {
                if (!query) {
                    return null
                }
                return setLatestVersionsOnQuery(
                    {
                        kind: NodeKind.ActorsQuery,
                        source: query,
                        select: selectFields,
                        orderBy: orderBy || [],
                        search: searchTerm,
                    },
                    { recursion: false }
                )
            },
        ],
        exploreUrl: [
            (s) => [s.actorsQuery],
            (actorsQuery): string | null => {
                if (!actorsQuery) {
                    return null
                }
                const { select: _select, ...source } = actorsQuery
                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source,
                    full: true,
                }
                return urls.insightNew({ query })
            },
        ],
        insightEventsQueryUrl: [
            (s) => [s.actorsQuery],
            (actorsQuery: ActorsQuery): string | null => {
                if (!actorsQuery) {
                    return null
                }

                // Generate insight events query from actors query
                const { select: _select, ...source } = actorsQuery

                const kind =
                    actorsQuery.source && 'source' in actorsQuery.source ? actorsQuery.source.source?.kind : null

                if (!kind || ![NodeKind.TrendsQuery].includes(kind)) {
                    return null
                }

                const { includeRecordings, ...insightActorsQuery } = source.source as InsightActorsQuery

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        source: insightActorsQuery,
                        select: ['*', 'event', 'person', 'timestamp'],
                        after: 'all', // Show all events by default because date range is filtered by the source
                    },
                    full: true,
                }

                return urls.insightNew({ query })
            },
        ],
    }),

    afterMount(({ actions, props }) => {
        actions.loadActors({ url: props.url })

        actions.reportPersonsModalViewed({
            url: props.url,
            query: props.query,
        })
    }),

    urlToAction(({ cache, actions }) => ({
        '*': (_a, _b, _c, { pathname }) => {
            if (!cache['lastPathname']) {
                cache['lastPathname'] = pathname
                return
            }
            // If we click anything that navigates us away, close the modal but
            // allowing for changes in hash due to the SessionsRecordings Modal
            if (cache['lastPathname'] !== pathname) {
                actions.closeModal()
            }
        },
    })),

    propsChanged(({ props, actions }, oldProps) => {
        if (props.url !== oldProps.url) {
            actions.loadActors({ url: props.url, clear: true })
        }
    }),
])
