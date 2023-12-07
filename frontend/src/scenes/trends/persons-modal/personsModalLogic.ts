import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { fromParamsGivenUrl, isGroupType } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { query as performQuery } from '~/queries/query'
import { InsightPersonsQuery, NodeKind, PersonsQuery } from '~/queries/schema'
import {
    ActorType,
    BreakdownType,
    ChartDisplayType,
    IntervalType,
    PersonActorType,
    PropertiesTimelineFilterType,
} from '~/types'

import type { personsModalLogicType } from './personsModalLogicType'

const RESULTS_PER_PAGE = 100

export interface PersonModalLogicProps {
    query?: InsightPersonsQuery | null
    url?: string | null
}

export interface ListActorsResponse {
    results: {
        count: number
        people: ActorType[]
    }[]
    missing_persons?: number
    next?: string
    next_offset?: number
}

export function wrapInsightsPersonsQuery(
    query: InsightPersonsQuery,
    search?: string,
    limit = RESULTS_PER_PAGE,
    offset = 0
): PersonsQuery {
    return {
        kind: NodeKind.PersonsQuery,
        source: query,
        select: ['person', 'groupArray(3)(pdi.distinct_id)'],
        orderBy: ['created_at DESC'],
        search,
        limit,
        offset,
    }
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
        loadActors: ({
            url,
            query,
            clear,
            offset,
        }): {
            url?: string | null
            query?: InsightPersonsQuery | null
            clear?: boolean
            offset?: number
        } => ({
            url,
            query,
            clear,
            offset,
        }),
        loadNextActors: true,
    }),
    connect({
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
        actions: [eventUsageLogic, ['reportCohortCreatedFromPersonsModal', 'reportPersonsModalViewed']],
    }),

    loaders(({ values, actions }) => ({
        actorsResponse: [
            null as ListActorsResponse | null,
            {
                loadActors: async ({ url, query, clear, offset }) => {
                    if (url) {
                        url += '&include_recordings=true'

                        if (values.searchTerm) {
                            url += `&search=${values.searchTerm}`
                        }

                        const res = await api.get(url)

                        if (clear) {
                            actions.resetActors()
                        }
                        return res
                    } else if (query) {
                        const personsQuery = wrapInsightsPersonsQuery(
                            query,
                            values.searchTerm,
                            RESULTS_PER_PAGE + 1,
                            offset || 0
                        )
                        const response = await performQuery(personsQuery)
                        const newResponse: ListActorsResponse = {
                            results: [
                                {
                                    count: response.results.length,
                                    people: response.results.slice(0, RESULTS_PER_PAGE).map(
                                        (result): PersonActorType => ({
                                            type: 'person',
                                            id: result[0].id,
                                            uuid: result[0].id,
                                            distinct_ids: result[1],
                                            is_identified: result[0].is_identified,
                                            properties: result[0].properties,
                                            created_at: result[0].created_at,
                                            matched_recordings: [],
                                            value_at_data_point: null,
                                        })
                                    ),
                                },
                            ],
                        }
                        if (response.results.length > RESULTS_PER_PAGE) {
                            newResponse.results[0].count = newResponse.results[0].people.length
                            newResponse.next_offset = (offset || 0) + newResponse.results[0].count
                        }
                        if (clear) {
                            actions.resetActors()
                        }
                        return newResponse
                    }
                    return null
                },
            },
        ],
    })),

    reducers(() => ({
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
            actions.loadActors({ query: props.query, url: props.url, clear: true })
        },
        saveAsCohort: async ({ cohortName }) => {
            const cohortParams = {
                is_static: true,
                name: cohortName,
            }
            if (props.query) {
                const {
                    limit: _,
                    offset: __,
                    ...personsQuery
                } = wrapInsightsPersonsQuery(props.query, values.searchTerm)
                const cohort = await api.create('api/cohort', { ...cohortParams, query: personsQuery })
                cohortsModel.actions.cohortCreated(cohort)
                lemonToast.success('Cohort saved', {
                    toastId: `cohort-saved-${cohort.id}`,
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(cohort.id)),
                    },
                })
                actions.setIsCohortModalOpen(false)
            } else {
                const qs = props.url?.split('?').pop() || ''
                const cohort = await api.create('api/cohort?' + qs, cohortParams)
                cohortsModel.actions.cohortCreated(cohort)
                lemonToast.success('Cohort saved', {
                    toastId: `cohort-saved-${cohort.id}`,
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(cohort.id)),
                    },
                })

                const filters = fromParamsGivenUrl('?' + qs)
                actions.setIsCohortModalOpen(false)
                actions.reportCohortCreatedFromPersonsModal(filters)
            }
        },
        loadNextActors: () => {
            if (values.actorsResponse?.next) {
                actions.loadActors({ url: values.actorsResponse.next })
            }
            if (values.actorsResponse?.next_offset) {
                actions.loadActors({ query: props.query, offset: values.actorsResponse.next_offset })
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
    }),

    afterMount(({ actions, props }) => {
        actions.loadActors({ query: props.query, url: props.url })

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
])
