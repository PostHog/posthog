import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { assignField, isGroupType, isSessionType } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { extractValidationError } from '~/queries/nodes/InsightViz/utils'
import { performQuery } from '~/queries/query'
import {
    ActorsQuery,
    DataTableNode,
    ExperimentActorsQuery,
    FunnelCorrelationActorsQuery,
    FunnelsActorsQuery,
    InsightActorsQuery,
    InsightActorsQueryOptions,
    InsightActorsQueryOptionsResponse,
    NodeKind,
    TrendsQuery,
    insightActorsQueryOptionsResponseKeys,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ActorType,
    BreakdownType,
    ChartDisplayType,
    CommonActorType,
    FilterLogicalOperator,
    GroupActorType,
    IntervalType,
    PersonActorType,
    PropertiesTimelineFilterType,
    SessionActorType,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    UniversalFilterValue,
} from '~/types'

import type { personsModalLogicType } from './personsModalLogicType'

const RESULTS_PER_PAGE = 100

// Scope session recordings to the funnel's selected breakdown value. Load-bearing:
// matched_recordings from the backend contains ALL of each actor's session IDs, so we
// need this filter to actually narrow the list. Returns null for breakdown types that
// can't be a single property filter (hogql / data_warehouse / multi-key / multi-value).
function buildFunnelBreakdownFilter(source: ActorsQuery['source'] | null): UniversalFilterValue | null {
    if (!source || source.kind !== NodeKind.FunnelsActorsQuery || source.funnelStepBreakdown == null) {
        return null
    }
    const breakdownFilter = source.source.breakdownFilter
    const breakdown = breakdownFilter?.breakdown
    const breakdownType = breakdownFilter?.breakdown_type ?? 'event'

    // Backend sends single values as one-element arrays (e.g. ["NL"]). Unwrap them; bail
    // for genuine multi-value arrays — a click represents one selected value.
    const rawBreakdownValue = source.funnelStepBreakdown
    let breakdownValue: string | number
    if (Array.isArray(rawBreakdownValue)) {
        if (rawBreakdownValue.length !== 1) {
            return null
        }
        breakdownValue = rawBreakdownValue[0]
    } else {
        breakdownValue = rawBreakdownValue
    }

    // Cohort → cohort membership filter. Skip the "All users" pseudo-cohort (0 / 'all').
    if (breakdownType === 'cohort') {
        if (breakdownValue === 0 || breakdownValue === 'all') {
            return null
        }
        const cohortId = typeof breakdownValue === 'number' ? breakdownValue : Number(breakdownValue)
        if (!Number.isFinite(cohortId)) {
            return null
        }
        return {
            type: PropertyFilterType.Cohort,
            key: 'id',
            value: cohortId,
            operator: PropertyOperator.In,
        }
    }

    // Non-cohort types need a single property key.
    if (!breakdown || Array.isArray(breakdown)) {
        return null
    }

    const key = String(breakdown)
    const base = { key, value: breakdownValue, operator: PropertyOperator.Exact }

    switch (breakdownType) {
        case 'event':
            return { ...base, type: PropertyFilterType.Event }
        case 'event_metadata':
            return { ...base, type: PropertyFilterType.EventMetadata }
        case 'person':
            return { ...base, type: PropertyFilterType.Person }
        case 'session':
            return { ...base, type: PropertyFilterType.Session }
        case 'group':
            if (breakdownFilter?.breakdown_group_type_index == null) {
                return null
            }
            return {
                ...base,
                type: PropertyFilterType.Group,
                group_type_index: breakdownFilter.breakdown_group_type_index,
            }
        // hogql / data_warehouse / revenue_analytics don't map to a single property filter.
        default:
            return null
    }
}

export interface PersonModalLogicProps {
    query?: InsightActorsQuery | FunnelsActorsQuery | FunnelCorrelationActorsQuery | ExperimentActorsQuery | null
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
        values: [groupsModel, ['groupTypes', 'aggregationLabel'], teamLogic, ['currentTeamId']],
        actions: [eventUsageLogic, ['reportPersonsModalViewed', 'reportPersonsModalSearched']],
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
                        const fieldKeys = Object.keys(props.additionalSelect || {}) as Array<keyof CommonActorType>
                        const fieldValues = Object.values(props.additionalSelect || {}) as Array<keyof CommonActorType>
                        const additionalFieldIndices = fieldValues.map((field) => assembledSelectFields.indexOf(field))
                        const personColumnIndex = (response.columns || []).indexOf('person')
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
                                            fieldKeys.forEach((field, index) => {
                                                assignField(group, field, result[additionalFieldIndices[index]])
                                            })
                                            return group
                                        }

                                        if (result[0].session_id !== undefined) {
                                            const session: SessionActorType = {
                                                type: 'session',
                                                id: result[0].session_id,
                                                properties: result[0],
                                                created_at: result[0].$start_timestamp,
                                                matched_recordings: [],
                                                value_at_data_point: null,
                                                person: personColumnIndex >= 0 ? result[personColumnIndex] : undefined,
                                            }
                                            fieldKeys.forEach((field, index) => {
                                                assignField(session, field, result[additionalFieldIndices[index]])
                                            })
                                            return session
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
                                        fieldKeys.forEach((field, index) => {
                                            assignField(person, field, result[additionalFieldIndices[index]])
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
        setSearchTerm: async ({ search }, breakpoint) => {
            await breakpoint(500)
            actions.loadActors({ url: props.url, clear: true })

            if (search) {
                actions.reportPersonsModalSearched({
                    teamId: values.currentTeamId,
                    actorType: values.actorLabel.singular,
                })
            }
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
                if (isSessionType(firstResult)) {
                    return { singular: 'session', plural: 'sessions' }
                }
                return aggregationLabel(isGroupType(firstResult) ? firstResult.group_type_index : undefined)
            },
        ],
        validationError: [
            (s) => [s.errorObject],
            (errorObject): string | null => {
                return extractValidationError(errorObject)
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
                const sourceTags = { ...query.source?.tags, ...query.tags }
                const activeScene = sceneLogic.findMounted()?.values.activeSceneId
                const tags = {
                    ...sourceTags,
                    ...(activeScene && !sourceTags.scene ? { scene: activeScene } : {}),
                }
                return setLatestVersionsOnQuery(
                    {
                        kind: NodeKind.ActorsQuery,
                        source: query,
                        select: selectFields,
                        orderBy: orderBy || [],
                        search: searchTerm,
                        ...(Object.keys(tags).length > 0 ? { tags } : {}),
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

                const { select: _select, ...source } = actorsQuery

                const kind =
                    actorsQuery.source && 'source' in actorsQuery.source ? actorsQuery.source.source?.kind : null

                if (!kind || ![NodeKind.TrendsQuery].includes(kind)) {
                    return null
                }

                const { includeRecordings, ...insightActorsQuery } = source.source as InsightActorsQuery

                const trendsQuery = insightActorsQuery.source as TrendsQuery
                const seriesIndex = insightActorsQuery.series ?? 0
                const seriesNode = trendsQuery.series?.[seriesIndex]
                const eventName = seriesNode && 'event' in seriesNode ? seriesNode.event : undefined

                const query: DataTableNode = {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        source: insightActorsQuery,
                        select: ['*', 'event', 'person', 'timestamp'],
                        // Show all events by default because date range is filtered by the source
                        after: 'all',
                        event: eventName,
                    },
                    full: true,
                }

                return urls.insightNew({ query })
            },
        ],
        sessionIdsFromLoadedActors: [
            (s) => [s.actors],
            (actors: ActorType[]): string[] => {
                // Extract all session IDs from loaded actors' matched_recordings
                const sessionIds: string[] = []
                actors.forEach((actor: ActorType) => {
                    if (actor.matched_recordings) {
                        actor.matched_recordings.forEach((recording) => {
                            if (recording.session_id) {
                                sessionIds.push(recording.session_id)
                            }
                        })
                    }
                })
                return sessionIds
            },
        ],
        recordingFilters: [
            (s) => [s.actorsQuery, s.propertiesTimelineFilterFromUrl, s.sessionIdsFromLoadedActors],
            (
                actorsQuery: ActorsQuery | null,
                propertiesTimelineFilter: PropertiesTimelineFilterType,
                sessionIds: string[]
            ): Partial<RecordingUniversalFilters> => {
                if (!actorsQuery || !actorsQuery.source) {
                    return {}
                }

                const source = actorsQuery.source

                // Scope recordings to the selected funnel breakdown value (e.g. country = "NL").
                const funnelBreakdownFilter = buildFunnelBreakdownFilter(source)

                // If we have session IDs from matched_recordings, use them directly for efficient lookup
                if (sessionIds.length > 0) {
                    return {
                        session_ids: sessionIds,
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [
                                {
                                    type: FilterLogicalOperator.And,
                                    values: funnelBreakdownFilter ? [funnelBreakdownFilter] : [],
                                },
                            ],
                        },
                        duration: [],
                    }
                }

                // For non-funnel queries or funnels without session IDs, use filter-based approach
                const filters: UniversalFilterValue[] = []

                // The actual insight query (with series, properties, etc.) is nested at source.source
                let insightQuery = source
                if ('source' in source && source.source) {
                    insightQuery = source.source as any
                }

                // Extract events from the insight query series
                if ('series' in insightQuery && Array.isArray(insightQuery.series)) {
                    insightQuery.series.forEach((series) => {
                        if ('event' in series && series.event) {
                            const eventFilter: any = {
                                id: series.event,
                                name: series.event,
                                type: 'events',
                            }
                            if (
                                'properties' in series &&
                                Array.isArray(series.properties) &&
                                series.properties.length > 0
                            ) {
                                eventFilter.properties = series.properties
                            }
                            filters.push(eventFilter)
                        }
                    })
                }

                // Add breakdown filters if present (trends path)
                if ('breakdown' in source && source.breakdown && propertiesTimelineFilter?.breakdown) {
                    const breakdownFilter = {
                        key: propertiesTimelineFilter.breakdown,
                        value: source.breakdown,
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    }
                    filters.push(breakdownFilter as UniversalFilterValue)
                }

                // Add breakdown filter for funnels
                if (funnelBreakdownFilter) {
                    filters.push(funnelBreakdownFilter)
                }

                // Add global properties from the insight query
                if (
                    'properties' in insightQuery &&
                    Array.isArray(insightQuery.properties) &&
                    insightQuery.properties.length > 0
                ) {
                    filters.push(...insightQuery.properties)
                }

                // Extract date range from insight query
                let date_from = propertiesTimelineFilter?.date_from
                let date_to = propertiesTimelineFilter?.date_to

                if ('dateRange' in insightQuery && insightQuery.dateRange) {
                    const dateRange = insightQuery.dateRange as any
                    date_from = dateRange.date_from || date_from
                    date_to = dateRange.date_to || date_to
                }

                // Build the result for non-funnel or fallback cases
                return {
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: filters,
                            },
                        ],
                    },
                    date_from,
                    date_to,
                }
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
