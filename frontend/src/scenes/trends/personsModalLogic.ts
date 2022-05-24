import { kea } from 'kea'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { convertPropertyGroupToProperties, fromParamsGivenUrl, isGroupType, toParams } from 'lib/utils'
import {
    ActionFilter,
    FilterType,
    InsightType,
    FunnelVizType,
    PropertyFilter,
    FunnelCorrelationResultsType,
    ActorType,
    GraphDataset,
    ChartDisplayType,
} from '~/types'
import type { personsModalLogicType } from './personsModalLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { TrendActors } from 'scenes/trends/types'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { filterTrendsClientSideParams } from 'scenes/insights/sharedUtils'
import { FEATURE_FLAGS } from 'lib/constants'
import { cohortsModel } from '~/models/cohortsModel'
import { dayjs } from 'lib/dayjs'
import { groupsModel } from '~/models/groupsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { urls } from 'scenes/urls'

export interface PersonsModalParams {
    action?: ActionFilter
    label: string // Contains the step name
    date_from: string | number
    date_to: string | number
    filters: Partial<FilterType>
    breakdown_value?: string | number
    saveOriginal?: boolean
    searchTerm?: string
    funnelStep?: number
    pathsDropoff?: boolean
    pointValue?: number // The y-axis value of the data point (i.e. count, unique persons, ...)
    crossDataset?: GraphDataset[]
    seriesId?: number
}

export interface PeopleParamType {
    action?: ActionFilter
    label: string
    date_to?: string | number
    date_from?: string | number
    breakdown_value?: string | number
    target_date?: number | string
    lifecycle_type?: string | number
}

export function parsePeopleParams(peopleParams: PeopleParamType, filters: Partial<FilterType>): string {
    const { action, date_from, date_to, breakdown_value, ...restParams } = peopleParams
    const params = filterTrendsClientSideParams({
        ...filters,
        entity_id: action?.id || filters?.events?.[0]?.id || filters?.actions?.[0]?.id,
        entity_type: action?.type || filters?.events?.[0]?.type || filters?.actions?.[0]?.type,
        entity_math: action?.math || undefined,
        breakdown_value,
    })

    // casting here is not the best
    if (filters.insight === InsightType.STICKINESS) {
        params.stickiness_days = date_from as number
    } else if (params.display === ChartDisplayType.ActionsLineGraphCumulative) {
        params.date_to = date_from as string
    } else if (filters.insight === InsightType.LIFECYCLE) {
        params.date_from = filters.date_from
        params.date_to = filters.date_to
    } else {
        params.date_from = date_from as string
        params.date_to = date_to as string
    }

    // If breakdown type is cohort, we use breakdown_value
    // If breakdown type is event, we just set another filter
    const flattenedPropertyGroup = convertPropertyGroupToProperties(params.properties)
    if (breakdown_value && filters.breakdown_type != 'cohort' && filters.breakdown_type != 'person') {
        params.properties = [
            ...(flattenedPropertyGroup || []),
            { key: params.breakdown, value: breakdown_value, type: 'event' } as PropertyFilter,
        ]
    }
    if (action?.properties) {
        params.properties = { ...(flattenedPropertyGroup || {}), ...action.properties }
    }

    return toParams({ ...params, ...restParams })
}

// Props for the `loadPeopleFromUrl` action.
// NOTE: this interface isn't particularly clean. Separation of concerns of load
// and displaying of people and the display of the modal would be helpful to
// keep this interfaces smaller.
export interface LoadPeopleFromUrlProps {
    // The url from which we can load urls
    url: string
    // The funnel step the dialog should display as the complete/dropped step.
    // Optional as this call signature includes any parameter from any insght type
    funnelStep?: number
    // Used to display in the modal title the property value we're filtering
    // with
    breakdown_value?: string | number // NOTE: using snake case to be consistent with the rest of the file
    // This label is used in the modal title. It's usage depends on the
    // filter.insight attribute. For insight=FUNNEL we use it as a person
    // property name
    label: string
    // Needed for display
    date_from?: string | number
    // Copied from `PersonsModalParams`, likely needed for display logic
    action?: ActionFilter
    // Copied from `PersonsModalParams`, likely needed for diplay logic
    pathsDropoff?: boolean
    // The y-axis value of the data point (i.e. count, unique persons, ...)
    pointValue?: number
    // Contains the data set for all the points in the same x-axis point; allows switching between matching points
    crossDataset?: GraphDataset[]
    // The frontend ID that identifies this particular series (i.e. if breakdowns are applied, each breakdown value is its own series)
    seriesId?: number
}

export const personsModalLogic = kea<personsModalLogicType>({
    path: ['scenes', 'trends', 'personsModalLogic'],
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
        setCohortModalVisible: (visible: boolean) => ({ visible }),
        loadPeople: (peopleParams: PersonsModalParams) => ({ peopleParams }),
        setUrl: (props: LoadPeopleFromUrlProps) => ({ props }),
        loadPeopleFromUrl: (props: LoadPeopleFromUrlProps) => props,
        switchToDataPoint: (seriesId: number) => ({ seriesId }), // Changes data point shown on PersonModal
        loadMorePeople: true,
        hidePeople: true,
        saveCohortWithUrl: (cohortName: string) => ({ cohortName }),
        setPersonsModalFilters: (searchTerm: string, people: TrendActors, filters: Partial<FilterType>) => ({
            searchTerm,
            people,
            filters,
        }),
        saveFirstLoadedActors: (people: TrendActors) => ({ people }),
        setFirstLoadedActors: (firstLoadedPeople: TrendActors | null) => ({ firstLoadedPeople }),
        openRecordingModal: (sessionRecordingId: string) => ({ sessionRecordingId }),
        closeRecordingModal: () => true,
    }),
    connect: {
        values: [groupsModel, ['groupTypes', 'aggregationLabel'], featureFlagLogic, ['featureFlags']],
        actions: [eventUsageLogic, ['reportCohortCreatedFromPersonsModal']],
    },
    reducers: () => ({
        sessionRecordingId: [
            null as null | string,
            {
                openRecordingModal: (_, { sessionRecordingId }) => sessionRecordingId,
                closeRecordingModal: () => null,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
                hidePeople: () => '',
            },
        ],
        cohortModalVisible: [
            false,
            {
                setCohortModalVisible: (_, { visible }) => visible,
            },
        ],
        people: [
            null as TrendActors | null,
            {
                loadPeople: (
                    _,
                    { peopleParams: { action, label, date_from, breakdown_value, crossDataset, seriesId } }
                ) => ({
                    people: [],
                    count: 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                    crossDataset,
                    seriesId,
                }),
                loadPeopleFromUrl: (_, { label, date_from = '', action, breakdown_value, crossDataset, seriesId }) => ({
                    people: [],
                    count: 0,
                    day: date_from,
                    label,
                    action,
                    breakdown_value,
                    crossDataset,
                    seriesId,
                }),
                setFilters: () => null,
                setFirstLoadedActors: (_, { firstLoadedPeople }) => firstLoadedPeople,
            },
        ],
        firstLoadedPeople: [
            null as TrendActors | null,
            {
                saveFirstLoadedActors: (_, { people }) => people,
            },
        ],
        loadingMorePeople: [
            false,
            {
                loadMorePeople: () => true,
                loadMorePeopleSuccess: () => false,
                loadMorePeopleFailure: () => false,
            },
        ],
        showingPeople: [
            false,
            {
                loadPeople: () => true,
                loadPeopleFromUrl: () => true,
                hidePeople: () => false,
            },
        ],
        peopleParams: [
            null as PersonsModalParams | null,
            {
                loadPeople: (_, { peopleParams }) => peopleParams,
            },
        ],
        peopleUrlParams: [
            // peopleParams when loaded from URL
            null as LoadPeopleFromUrlProps | null,
            {
                loadPeopleFromUrl: (_, props) => props,
                setUrl: (_, { props }) => props,
            },
        ],
    }),
    selectors: {
        isInitialLoad: [
            (s) => [s.peopleLoading, s.loadingMorePeople],
            (peopleLoading, loadingMorePeople) => peopleLoading && !loadingMorePeople,
        ],
        isGroupType: [(s) => [s.people], (people) => people?.people?.[0] && isGroupType(people.people[0])],
        actorLabel: [
            (s) => [s.people, s.isGroupType, s.groupTypes, s.aggregationLabel],
            (result, _isGroupType, groupTypes, aggregationLabel) => {
                if (_isGroupType) {
                    return result?.action?.math_group_type_index != undefined &&
                        groupTypes.length > result?.action.math_group_type_index
                        ? aggregationLabel(result?.action.math_group_type_index).plural
                        : ''
                } else {
                    return 'persons'
                }
            },
        ],
    },
    loaders: ({ actions, values }) => ({
        people: {
            loadPeople: async ({ peopleParams }, breakpoint) => {
                let actors: PaginatedResponse<{
                    people: ActorType[]
                    count: number
                }> | null = null
                const {
                    label,
                    action,
                    filters,
                    date_from,
                    date_to,
                    breakdown_value,
                    saveOriginal,
                    searchTerm,
                    funnelStep,
                    pathsDropoff,
                    crossDataset,
                    seriesId,
                } = peopleParams

                const searchTermParam = searchTerm ? `&search=${encodeURIComponent(searchTerm)}` : ''

                if (filters.funnel_correlation_person_entity) {
                    const cleanedParams = cleanFilters(filters)
                    actors = await api.create(`api/person/funnel/correlation/?${searchTermParam}`, cleanedParams)
                } else if (filters.insight === InsightType.LIFECYCLE) {
                    const filterParams = parsePeopleParams(
                        { label, action, target_date: date_from, lifecycle_type: breakdown_value },
                        filters
                    )
                    actors = await api.get(`api/person/lifecycle/?${filterParams}${searchTermParam}`)
                } else if (filters.insight === InsightType.STICKINESS) {
                    const filterParams = parsePeopleParams(
                        { label, action, date_from, date_to, breakdown_value },
                        filters
                    )
                    actors = await api.get(`api/person/stickiness/?${filterParams}${searchTermParam}`)
                } else if (funnelStep || filters.funnel_viz_type === FunnelVizType.Trends) {
                    let params
                    if (filters.funnel_viz_type === FunnelVizType.Trends) {
                        // funnel trends
                        const entrance_period_start = dayjs(date_from).format('YYYY-MM-DD HH:mm:ss')
                        params = { ...filters, entrance_period_start, drop_off: false }
                    } else {
                        // regular funnel steps
                        params = {
                            ...filters,
                            funnel_step: funnelStep,
                            ...(breakdown_value !== undefined && { funnel_step_breakdown: breakdown_value }),
                        }

                        // getting property correlations from funnel
                        if (params.funnel_custom_steps) {
                            eventUsageLogic.actions.reportCorrelationInteraction(
                                FunnelCorrelationResultsType.Properties,
                                'person modal',
                                filters.funnel_correlation_person_entity
                            )
                        }
                    }
                    const cleanedParams = cleanFilters(params)
                    const funnelParams = toParams(cleanedParams)
                    let includeRecordingsParam = ''
                    if (values.featureFlags[FEATURE_FLAGS.RECORDINGS_IN_INSIGHTS]) {
                        includeRecordingsParam = 'include_recordings=true&'
                    }
                    actors = await api.create(
                        `api/person/funnel/?${includeRecordingsParam}${funnelParams}${searchTermParam}`
                    )
                } else if (filters.insight === InsightType.PATHS) {
                    const cleanedParams = cleanFilters(filters)
                    const pathParams = toParams(cleanedParams)

                    let includeRecordingsParam = ''
                    if (values.featureFlags[FEATURE_FLAGS.RECORDINGS_IN_INSIGHTS]) {
                        includeRecordingsParam = 'include_recordings=true&'
                    }
                    actors = await api.create(
                        `api/person/path/?${includeRecordingsParam}${searchTermParam}`,
                        cleanedParams
                    )

                    // Manually populate URL data so that cohort creation can use this information
                    const pathsParams = {
                        url: `api/person/path/paths/?${pathParams}`,
                        funnelStep,
                        breakdown_value,
                        label,
                        date_from,
                        action,
                        pathsDropoff,
                        crossDataset,
                        seriesId,
                    }
                    actions.setUrl(pathsParams)
                } else {
                    actors = await api.actions.getPeople(
                        { label, action, date_from, date_to, breakdown_value },
                        filters,
                        searchTerm
                    )
                }
                breakpoint()
                const peopleResult = {
                    people: actors?.results[0]?.people,
                    count: actors?.results[0]?.count || 0,
                    action,
                    label,
                    day: date_from,
                    breakdown_value,
                    next: actors?.next,
                    funnelStep,
                    pathsDropoff,
                    crossDataset,
                    seriesId,
                } as TrendActors

                eventUsageLogic.actions.reportPersonsModalViewed(peopleParams, peopleResult.count, !!actors?.next)

                if (saveOriginal) {
                    actions.saveFirstLoadedActors(peopleResult)
                }

                return peopleResult
            },
            loadPeopleFromUrl: async ({
                url,
                funnelStep,
                breakdown_value = '',
                date_from = '',
                action,
                label,
                pathsDropoff,
                crossDataset,
                seriesId,
            }) => {
                if (values.featureFlags[FEATURE_FLAGS.RECORDINGS_IN_INSIGHTS]) {
                    // A bit hacky (doesn't account for hash params),
                    // but it works and only needed while we have this feature flag
                    url += '&include_recordings=true'
                }
                const people = await api.get(url)
                return {
                    people: people?.results[0]?.people,
                    count: people?.results[0]?.count || 0,
                    label,
                    funnelStep,
                    breakdown_value,
                    day: date_from,
                    action: action,
                    next: people?.next,
                    pathsDropoff,
                    crossDataset,
                    seriesId,
                }
            },
            loadMorePeople: async ({}, breakpoint) => {
                if (values.people) {
                    const {
                        people: currPeople,
                        count,
                        action,
                        label,
                        day,
                        breakdown_value,
                        next,
                        funnelStep,
                        crossDataset,
                        seriesId,
                    } = values.people
                    if (!next) {
                        throw new Error('URL of next page of persons is not known.')
                    }
                    const people = await api.get(next)
                    breakpoint()

                    return {
                        people: [...currPeople, ...people.results[0]?.people],
                        count: count + people.results[0]?.count,
                        action,
                        label,
                        day,
                        breakdown_value,
                        next: people.next,
                        funnelStep,
                        crossDataset,
                        seriesId,
                    }
                }
                return null
            },
        },
    }),
    listeners: ({ actions, values }) => ({
        saveCohortWithUrl: async ({ cohortName }) => {
            if (values.people && values.peopleUrlParams?.url) {
                const cohortParams = {
                    is_static: true,
                    name: cohortName,
                }

                const qs = values.peopleUrlParams.url.split('?').pop() || ''
                const cohort = await api.create('api/cohort?' + qs, cohortParams)
                cohortsModel.actions.cohortCreated(cohort)
                lemonToast.success('Cohort saved', {
                    toastId: `cohort-saved-${cohort.id}`,
                    button: {
                        label: 'View cohort',
                        action: () => router.actions.push(urls.cohort(cohort.id)),
                    },
                })

                const filters = fromParamsGivenUrl('?' + qs) // this function expects the question mark to be included
                actions.reportCohortCreatedFromPersonsModal(filters)
            } else {
                lemonToast.error("The cohort couldn't be created")
            }
        },
        setPersonsModalFilters: async ({ searchTerm, people, filters }) => {
            const { label, action, day, breakdown_value, funnelStep, crossDataset, seriesId } = people
            const date_from = day
            const date_to = day
            const saveOriginal = false
            actions.loadPeople({
                action,
                label,
                date_from,
                date_to,
                filters,
                breakdown_value,
                saveOriginal,
                searchTerm,
                funnelStep,
                crossDataset,
                seriesId,
            })
        },
        switchToDataPoint: async ({ seriesId }) => {
            const data = values.people?.crossDataset?.find(({ id: _id }) => _id === seriesId)

            if (data && data.action) {
                const commonParams = {
                    seriesId,
                    breakdown_value: data.breakdown_value,
                    action: data.action,
                    pointValue: data.pointValue,
                }
                if (values.peopleParams) {
                    actions.loadPeople({
                        ...values.peopleParams,
                        ...commonParams,
                    })
                }
                if (data.personUrl && values.peopleUrlParams) {
                    actions.loadPeopleFromUrl({
                        ...values.peopleUrlParams,
                        ...commonParams,
                        url: data.personUrl,
                    })
                }
            }
        },
    }),
    actionToUrl: () => ({
        openRecordingModal: ({ sessionRecordingId }) => {
            return [
                router.values.location.pathname,
                { ...router.values.searchParams },
                { ...router.values.hashParams, sessionRecordingId },
            ]
        },
        closeRecordingModal: () => {
            delete router.values.hashParams.sessionRecordingId
            return [router.values.location.pathname, { ...router.values.searchParams }, { ...router.values.hashParams }]
        },
    }),
})
