import { kea } from 'kea'
import api from 'lib/api'
import { cohortsModel } from '~/models/cohortsModel'
import { ENTITY_MATCH_TYPE, FEATURE_FLAGS, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { cohortLogicType } from './cohortLogicType'
import {
    AnyCohortCriteriaType,
    AnyCohortGroupType,
    BehavioralEventType,
    Breadcrumb,
    CohortCriteriaGroupFilter,
    CohortGroupType,
    CohortType,
    FilterLogicalOperator,
    TimeUnitType,
} from '~/types'
import { convertPropertyGroupToProperties } from 'lib/utils'
import { personsLogic } from 'scenes/persons/personsLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey } from 'scenes/cohorts/CohortFilters/types'
import { isCohortCriteriaGroup } from 'scenes/cohorts/CohortFilters/cohortUtils'

function createCohortFormData(cohort: CohortType): FormData {
    const rawCohort = {
        ...cohort,
        groups: JSON.stringify(
            cohort.is_static
                ? []
                : cohort.groups.map((group: CohortGroupType) => ({ ...group, id: undefined, matchType: undefined }))
        ),
    }
    // Must use FormData to encode file binary in request
    const cohortFormData = new FormData()
    for (const [itemKey, value] of Object.entries(rawCohort)) {
        cohortFormData.append(itemKey, value as string | Blob)
    }
    return cohortFormData
}

function addLocalCohortGroupId(group: Partial<CohortGroupType>): CohortGroupType {
    const matchType = group.action_id || group.event_id ? ENTITY_MATCH_TYPE : PROPERTY_MATCH_TYPE

    return {
        matchType,
        id: Math.random().toString().substr(2, 5),
        ...group,
    }
}

function processCohortOnSet(cohort: CohortType, isGroup: boolean = false): CohortType {
    return {
        ...cohort,
        ...(isGroup
            ? {
                  properties: cohort.properties,
              }
            : {
                  groups:
                      cohort.groups?.map((group) => ({
                          ...addLocalCohortGroupId(group),
                          ...(group.properties
                              ? { properties: convertPropertyGroupToProperties(group.properties) }
                              : {}),
                      })) ?? [],
              }),
    }
}

export const NEW_CRITERIA = {
    type: BehavioralFilterKey.Behavioral,
    value: BehavioralEventType.PerformEvent,
    event_type: TaxonomicFilterGroupType.Events,
    time_value: 30,
    time_interval: TimeUnitType.Day,
}

export const NEW_CRITERIA_GROUP = {
    type: FilterLogicalOperator.Or,
    values: [NEW_CRITERIA],
}

export const NEW_COHORT: CohortType = {
    id: 'new',
    groups: [
        {
            id: Math.random().toString().substr(2, 5),
            matchType: PROPERTY_MATCH_TYPE,
            properties: [],
        },
    ],
    properties: {
        type: FilterLogicalOperator.Or,
        values: [NEW_CRITERIA_GROUP],
    },
}

export interface CohortLogicProps {
    id?: CohortType['id']
}

export const cohortLogic = kea<cohortLogicType<CohortLogicProps>>({
    props: {} as CohortLogicProps,
    key: (props) => props.id || 'new',
    path: (key) => ['scenes', 'cohorts', 'cohortLogic', key],

    actions: () => ({
        saveCohort: (cohortParams = {}, filterParams = null) => ({ cohortParams, filterParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: true,
        fetchCohort: (id: CohortType['id']) => ({ id }),
        onCriteriaChange: (newGroup: Partial<CohortGroupType>, id: string) => ({ newGroup, id }),
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),

        setOuterGroupsType: (type: FilterLogicalOperator) => ({ type }),
        setInnerGroupType: (type: FilterLogicalOperator, groupIndex: number) => ({ type, groupIndex }),
        duplicateFilter: (groupIndex: number, criteriaIndex?: number) => ({ groupIndex, criteriaIndex }),
        addFilter: (groupIndex?: number) => ({ groupIndex }),
        removeFilter: (groupIndex: number, criteriaIndex?: number) => ({ groupIndex, criteriaIndex }),
        setCriteria: (newCriteria: Partial<AnyCohortCriteriaType>, groupIndex: number, criteriaIndex: number) => ({
            newCriteria,
            groupIndex,
            criteriaIndex,
        }),
    }),

    reducers: () => ({
        cohort: [
            NEW_COHORT as CohortType,
            {
                onCriteriaChange: (state, { newGroup, id }) => {
                    const cohort = { ...state }
                    const index = cohort.groups.findIndex((group: AnyCohortGroupType) => group.id === id)
                    if (newGroup.matchType) {
                        cohort.groups[index] = {
                            id: cohort.groups[index].id,
                            matchType: ENTITY_MATCH_TYPE,
                            ...newGroup,
                        }
                    } else {
                        cohort.groups[index] = {
                            ...cohort.groups[index],
                            ...newGroup,
                        }
                    }
                    return processCohortOnSet(cohort)
                },
                setOuterGroupsType: (state, { type }) => ({
                    ...state,
                    properties: {
                        ...state.properties,
                        type,
                    },
                }),
                setInnerGroupType: (state, { type, groupIndex }) => ({
                    ...state,
                    properties: {
                        ...state.properties,
                        values: state.properties.values.map((group, groupI) =>
                            groupI === groupIndex
                                ? {
                                      ...group,
                                      type,
                                  }
                                : group
                        ) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                    },
                }),
                duplicateFilter: (state, { groupIndex, criteriaIndex }) => {
                    const newFilters = { ...state }

                    if (criteriaIndex !== undefined) {
                        return {
                            ...newFilters,
                            properties: {
                                ...newFilters.properties,
                                values: newFilters.properties.values.map((group, groupI) =>
                                    groupI === groupIndex && isCohortCriteriaGroup(group)
                                        ? {
                                              ...group,
                                              values: [
                                                  ...group.values.slice(0, criteriaIndex),
                                                  group.values[criteriaIndex],
                                                  ...group.values.slice(criteriaIndex),
                                              ],
                                          }
                                        : group
                                ) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                            },
                        }
                    }

                    return {
                        ...newFilters,
                        properties: {
                            ...newFilters.properties,
                            values: [
                                ...newFilters.properties.values.slice(0, groupIndex),
                                newFilters.properties.values[groupIndex],
                                ...newFilters.properties.values.slice(groupIndex),
                            ] as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                        },
                    }
                },
                addFilter: (state, { groupIndex }) => {
                    const newFilters = { ...state }

                    if (groupIndex !== undefined) {
                        return {
                            ...newFilters,
                            properties: {
                                ...newFilters.properties,
                                values: newFilters.properties.values.map((group, groupI) =>
                                    groupI === groupIndex && isCohortCriteriaGroup(group)
                                        ? {
                                              ...group,
                                              values: [...group.values, NEW_CRITERIA],
                                          }
                                        : group
                                ) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                            },
                        }
                    }
                    return {
                        ...newFilters,
                        properties: {
                            ...newFilters.properties,
                            values: [...newFilters.properties.values, NEW_CRITERIA_GROUP] as
                                | CohortCriteriaGroupFilter[]
                                | AnyCohortCriteriaType[],
                        },
                    }
                },
                removeFilter: (state, { groupIndex, criteriaIndex }) => {
                    const newFilters = { ...state }

                    if (criteriaIndex !== undefined) {
                        return {
                            ...newFilters,
                            properties: {
                                ...newFilters.properties,
                                values: newFilters.properties.values.map((group, groupI) =>
                                    groupI === groupIndex && isCohortCriteriaGroup(group)
                                        ? {
                                              ...group,
                                              values: [
                                                  ...group.values.slice(0, criteriaIndex),
                                                  ...group.values.slice(criteriaIndex + 1),
                                              ],
                                          }
                                        : group
                                ) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                            },
                        }
                    }
                    return {
                        ...newFilters,
                        properties: {
                            ...newFilters.properties,
                            values: [
                                ...newFilters.properties.values.slice(0, groupIndex),
                                ...newFilters.properties.values.slice(groupIndex + 1),
                            ] as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                        },
                    }
                },
                setCriteria: (state, { newCriteria, groupIndex, criteriaIndex }) => {
                    const newFilters = { ...state }

                    console.log('SET', newCriteria, groupIndex, criteriaIndex)

                    console.log('SETFINALE', newFilters, {
                        ...newFilters,
                        properties: {
                            ...newFilters.properties,
                            values: newFilters.properties.values.map((group, groupI) =>
                                groupI === groupIndex && isCohortCriteriaGroup(group)
                                    ? {
                                          ...group,
                                          values: group.values.map((criteria, criteriaI) =>
                                              criteriaI === criteriaIndex
                                                  ? {
                                                        ...criteria,
                                                        ...newCriteria,
                                                    }
                                                  : criteria
                                          ),
                                      }
                                    : group
                            ) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                        },
                    })

                    return {
                        ...newFilters,
                        properties: {
                            ...newFilters.properties,
                            values: newFilters.properties.values.map((group, groupI) =>
                                groupI === groupIndex && isCohortCriteriaGroup(group)
                                    ? {
                                          ...group,
                                          values: group.values.map((criteria, criteriaI) =>
                                              criteriaI === criteriaIndex
                                                  ? {
                                                        ...criteria,
                                                        ...newCriteria,
                                                    }
                                                  : criteria
                                          ),
                                      }
                                    : group
                            ) as CohortCriteriaGroupFilter[] | AnyCohortCriteriaType[],
                        },
                    }
                },
            },
        ],
        pollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
    }),

    forms: ({ actions }) => ({
        cohort: {
            defaults: NEW_COHORT,
            validator: ({ name, csv, is_static, groups }) => ({
                name: !name ? 'You need to set a name' : undefined,
                csv: is_static && !csv ? 'You need to upload a CSV file' : (null as any),
                // Return type of validator[groups](...) must be the shape of groups. Returning the error message
                // for groups as a value for id is a hacky stopgap.
                groups: is_static
                    ? undefined
                    : !groups || groups.length < 1
                    ? [{ id: 'You need at least one matching group' }]
                    : groups?.map(({ matchType, properties, action_id, event_id }) => {
                          if (matchType === PROPERTY_MATCH_TYPE && !properties?.length) {
                              return { id: 'Please select at least one property or remove this match group.' }
                          }
                          if (matchType === ENTITY_MATCH_TYPE && !(action_id || event_id)) {
                              return { id: 'Please select an event or action.' }
                          }
                          return { id: undefined }
                      }),
            }),
            submit: (cohort) => {
                actions.saveCohort(cohort)
            },
        },
    }),

    loaders: ({ actions, values, key }) => ({
        cohort: [
            NEW_COHORT as CohortType,
            {
                setCohort: ({ cohort }) => {
                    return processCohortOnSet(cohort)
                },
                fetchCohort: async ({ id }, breakpoint) => {
                    try {
                        const cohort = await api.cohorts.get(id)
                        breakpoint()
                        cohortsModel.actions.updateCohort(cohort)
                        actions.checkIfFinishedCalculating(cohort)
                        return processCohortOnSet(cohort)
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to fetch cohort')
                        return values.cohort
                    }
                },
                saveCohort: async ({ cohortParams, filterParams }, breakpoint) => {
                    let cohort = { ...values.cohort, ...cohortParams }
                    const cohortFormData = createCohortFormData(cohort)

                    try {
                        if (cohort.id !== 'new') {
                            cohort = await api.cohorts.update(
                                cohort.id,
                                cohortFormData as Partial<CohortType>,
                                filterParams
                            )
                            cohortsModel.actions.updateCohort(cohort)
                        } else {
                            cohort = await api.cohorts.create(cohortFormData as Partial<CohortType>, filterParams)
                            cohortsModel.actions.cohortCreated(cohort)
                        }
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to save cohort')
                        return values.cohort
                    }

                    cohort.is_calculating = true // this will ensure there is always a polling period to allow for backend calculation task to run
                    breakpoint()
                    delete cohort['csv']
                    actions.setCohort(cohort)
                    lemonToast.success('Cohort saved. Please wait up to a few minutes for it to be calculated', {
                        toastId: `cohort-saved-${key}`,
                    })
                    return cohort
                },
            },
        ],
    }),

    selectors: {
        newCohortFiltersEnabled: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.COHORT_FILTERS],
        ],
        breadcrumbs: [
            (s) => [s.cohort],
            (cohort): Breadcrumb[] => [
                {
                    name: 'Cohorts',
                    path: urls.cohorts(),
                },
                ...(cohort ? [{ name: cohort.name || 'Untitled' }] : []),
            ],
        ],
    },

    listeners: ({ actions, values }) => ({
        deleteCohort: () => {
            cohortsModel.findMounted()?.actions.deleteCohort(values.cohort)
            router.actions.push(urls.cohorts())
        },
        checkIfFinishedCalculating: async ({ cohort }, breakpoint) => {
            if (cohort.is_calculating) {
                actions.setPollTimeout(
                    setTimeout(async () => {
                        const newCohort = await api.cohorts.get(cohort.id)
                        breakpoint()
                        actions.checkIfFinishedCalculating(newCohort)
                    }, 1000)
                )
            } else {
                actions.setCohort(cohort)
                cohortsModel.actions.updateCohort(cohort)
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts() // To ensure sync on person page
                if (values.pollTimeout) {
                    clearTimeout(values.pollTimeout)
                    actions.setPollTimeout(null)
                }
            }
        },
    }),

    actionToUrl: ({ values }) => ({
        saveCohortSuccess: () => urls.cohort(values.cohort.id),
    }),

    events: ({ values, actions, props }) => ({
        afterMount: async () => {
            if (!props.id || props.id === 'new') {
                actions.setCohort(NEW_COHORT)
            } else {
                actions.fetchCohort(props.id)
            }
        },
        beforeUnmount: () => {
            if (values.pollTimeout) {
                clearTimeout(values.pollTimeout)
            }
        },
    }),
})
