import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { v4 as uuidv4 } from 'uuid'

import api, { CountedPaginatedResponse } from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME } from 'scenes/cohorts/CohortFilters/constants'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { personsLogic } from 'scenes/persons/personsLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { deleteFromTree, refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import {
    AnyCohortCriteriaType,
    BehavioralCohortType,
    BehavioralEventType,
    CohortCriteriaGroupFilter,
    CohortType,
} from '~/types'

import type { cohortsModelType } from './cohortsModelType'

const POLL_TIMEOUT = 5000

export const COHORTS_PER_PAGE = 100

export const MAX_COHORTS_FOR_FULL_LIST = 2000

export interface CohortFilters {
    search?: string
    page?: number
}

export const DEFAULT_COHORT_FILTERS: CohortFilters = {
    search: undefined,
    page: 1,
}

export function processCohort(cohort: CohortType): CohortType {
    return {
        ...cohort,

        /* Populate value_property with value and overwrite value with corresponding behavioral filter type */
        filters: {
            properties: {
                ...cohort.filters.properties,
                values: (cohort.filters.properties?.values?.map((group) =>
                    'values' in group
                        ? {
                              ...group,
                              values: (group.values as AnyCohortCriteriaType[]).map((c) => processCohortCriteria(c)),
                              sort_key: uuidv4(),
                          }
                        : group
                ) ?? []) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
            },
        },
    }
}

function convertTimeValueToRelativeTime(criteria: AnyCohortCriteriaType): string | undefined {
    const timeValue = criteria?.time_value
    const timeInterval = criteria?.time_interval

    if (timeValue && timeInterval) {
        return `-${timeValue}${timeInterval[0]}`
    }
}

function processCohortCriteria(criteria: AnyCohortCriteriaType): AnyCohortCriteriaType {
    if (!criteria.type) {
        return criteria
    }

    const processedCriteria = { ...criteria }

    if (
        [BehavioralFilterKey.Cohort, BehavioralFilterKey.Person].includes(criteria.type) &&
        !('value_property' in criteria)
    ) {
        processedCriteria.value_property = criteria.value
        processedCriteria.value =
            criteria.type === BehavioralFilterKey.Cohort
                ? BehavioralCohortType.InCohort
                : BehavioralEventType.HaveProperty
    }

    if (
        [BehavioralFilterKey.Behavioral].includes(criteria.type) &&
        !('explicit_datetime' in criteria) &&
        criteria.value &&
        COHORT_EVENT_TYPES_WITH_EXPLICIT_DATETIME.includes(criteria.value)
    ) {
        processedCriteria.explicit_datetime = convertTimeValueToRelativeTime(criteria)
    }

    if (processedCriteria.sort_key == null) {
        processedCriteria.sort_key = uuidv4()
    }

    return processedCriteria
}

export const cohortsModel = kea<cohortsModelType>([
    path(['models', 'cohortsModel']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions(() => ({
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
        updateCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: (cohort: Partial<CohortType>) => ({ cohort }),
        cohortCreated: (cohort: CohortType) => ({ cohort }),
    })),
    loaders(() => ({
        cohorts: {
            __default: { count: 0, results: [] } as CountedPaginatedResponse<CohortType>,
            loadCohorts: async () => {
                const response = await api.cohorts.listPaginated({
                    limit: MAX_COHORTS_FOR_FULL_LIST,
                })
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts()
                return {
                    count: response.count,
                    results: response.results.map((cohort) => processCohort(cohort)),
                }
            },
        },
        allCohorts: {
            __default: { count: 0, results: [] } as CountedPaginatedResponse<CohortType>,
            loadAllCohorts: async () => {
                const response = await api.cohorts.listPaginated({
                    limit: MAX_COHORTS_FOR_FULL_LIST,
                })
                return {
                    count: response.count,
                    results: response.results.map((cohort) => processCohort(cohort)),
                }
            },
        },
    })),
    reducers({
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohorts: {
            updateCohort: (state, { cohort }) => {
                if (!cohort) {
                    return state
                }
                return {
                    ...state,
                    results: state.results.map((existingCohort) =>
                        existingCohort.id === cohort.id ? cohort : existingCohort
                    ),
                }
            },
            cohortCreated: (state, { cohort }) => {
                if (!cohort) {
                    return state
                }
                return {
                    ...state,
                    results: [cohort, ...state.results],
                }
            },
            deleteCohort: (state, { cohort }) => {
                if (!cohort.id) {
                    return state
                }
                return {
                    ...state,
                    results: state.results.filter((c) => c.id !== cohort.id),
                }
            },
        },
        // Update allCohorts state to keep breadcrumbs in sync when cohorts are modified
        // The cohortsById selector depends on allCohorts, not cohorts
        allCohorts: {
            updateCohort: (state, { cohort }) => {
                if (!cohort) {
                    return state
                }
                return {
                    ...state,
                    results: state.results.map((existingCohort) =>
                        existingCohort.id === cohort.id ? cohort : existingCohort
                    ),
                }
            },
            cohortCreated: (state, { cohort }) => {
                if (!cohort) {
                    return state
                }
                return {
                    ...state,
                    results: [cohort, ...state.results],
                }
            },
            deleteCohort: (state, { cohort }) => {
                if (!cohort.id) {
                    return state
                }
                return {
                    ...state,
                    results: state.results.filter((c) => c.id !== cohort.id),
                }
            },
        },
    }),
    selectors({
        cohortsById: [
            (s) => [s.allCohorts],
            (allCohorts): Partial<Record<string | number, CohortType>> =>
                Object.fromEntries(allCohorts.results.map((cohort) => [cohort.id, cohort])),
        ],
        count: [(selectors) => [selectors.cohorts], (cohorts) => cohorts.count],
    }),
    listeners(({ actions }) => ({
        loadCohortsSuccess: async ({ cohorts }: { cohorts: CountedPaginatedResponse<CohortType> }) => {
            const is_calculating = cohorts.results.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadCohorts, POLL_TIMEOUT))
        },
        loadAllCohortsSuccess: async ({ allCohorts }: { allCohorts: CountedPaginatedResponse<CohortType> }) => {
            const is_calculating = allCohorts.results.filter((cohort) => cohort.is_calculating).length > 0
            if (!is_calculating || !router.values.location.pathname.includes(urls.cohorts())) {
                return
            }
            actions.setPollTimeout(window.setTimeout(actions.loadAllCohorts, POLL_TIMEOUT))
        },
        deleteCohort: async ({ cohort }) => {
            await deleteWithUndo({
                endpoint: api.cohorts.determineDeleteEndpoint(),
                object: cohort,
                callback: (undo) => {
                    actions.loadCohorts()
                    if (cohort.id && cohort.id !== 'new') {
                        if (undo) {
                            refreshTreeItem('cohort', String(cohort.id))
                        } else {
                            deleteFromTree('cohort', String(cohort.id))
                            router.actions.push(urls.cohorts())
                        }
                    }
                },
            })
        },
    })),
    beforeUnmount(({ values }) => {
        clearTimeout(values.pollTimeout || undefined)
    }),
    afterMount(({ actions, values }) => {
        if (isAuthenticatedTeam(values.currentTeam)) {
            // Don't load on shared insights/dashboards
            actions.loadAllCohorts()
        }
        actions.loadCohorts()
    }),
    permanentlyMount(),
])
