import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'
import api from 'lib/api'
import { ENTITY_MATCH_TYPE } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { NEW_COHORT, NEW_CRITERIA, NEW_CRITERIA_GROUP } from 'scenes/cohorts/CohortFilters/constants'
import {
    applyAllCriteriaGroup,
    applyAllNestedCriteria,
    cleanCriteria,
    createCohortFormData,
    isCohortCriteriaGroup,
    validateGroup,
} from 'scenes/cohorts/cohortUtils'
import { personsLogic } from 'scenes/persons/personsLogic'
import { urls } from 'scenes/urls'
import { v4 as uuidv4 } from 'uuid'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { cohortsModel, processCohort } from '~/models/cohortsModel'
import { DataTableNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { isDataTableNode } from '~/queries/utils'
import {
    AnyCohortCriteriaType,
    AnyCohortGroupType,
    CohortCriteriaGroupFilter,
    CohortGroupType,
    CohortType,
    FilterLogicalOperator,
    PropertyFilterType,
} from '~/types'

import type { cohortEditLogicType } from './cohortEditLogicType'

export type CohortLogicProps = {
    id?: CohortType['id']
}

export const cohortEditLogic = kea<cohortEditLogicType>([
    props({} as CohortLogicProps),
    key((props) => props.id || 'new'),
    path(['scenes', 'cohorts', 'cohortLogicEdit']),
    connect(() => ({
        actions: [eventUsageLogic, ['reportExperimentExposureCohortEdited']],
    })),

    actions({
        saveCohort: (cohortParams = {}) => ({ cohortParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: true,
        fetchCohort: (id: CohortType['id']) => ({ id }),
        setCohortMissing: true,
        onCriteriaChange: (newGroup: Partial<CohortGroupType>, id: string) => ({ newGroup, id }),
        setPollTimeout: (pollTimeout: number | null) => ({ pollTimeout }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),

        setOuterGroupsType: (type: FilterLogicalOperator) => ({ type }),
        setInnerGroupType: (type: FilterLogicalOperator, groupIndex: number) => ({ type, groupIndex }),
        duplicateFilter: (groupIndex: number, criteriaIndex?: number) => ({ groupIndex, criteriaIndex }),
        addFilter: (groupIndex?: number) => ({ groupIndex }),
        removeFilter: (groupIndex: number, criteriaIndex?: number) => ({ groupIndex, criteriaIndex }),
        setCriteria: (newCriteria: AnyCohortCriteriaType, groupIndex: number, criteriaIndex: number) => ({
            newCriteria,
            groupIndex,
            criteriaIndex,
        }),
        setQuery: (query: Node) => ({ query }),
        duplicateCohort: (asStatic: boolean) => ({ asStatic }),
    }),

    reducers(({ props }) => ({
        cohort: [
            NEW_COHORT,
            {
                setOuterGroupsType: (state, { type }) => ({
                    ...state,
                    filters: {
                        properties: {
                            ...state.filters.properties,
                            type,
                        },
                    },
                }),
                setInnerGroupType: (state, { type, groupIndex }) =>
                    applyAllCriteriaGroup(
                        state,
                        (groupList) =>
                            groupList.map((group, groupI) =>
                                groupI === groupIndex ? { ...group, type } : group
                            ) as CohortCriteriaGroupFilter[]
                    ),
                duplicateFilter: (state, { groupIndex, criteriaIndex }) => {
                    if (criteriaIndex !== undefined) {
                        return applyAllNestedCriteria(
                            state,
                            (criteriaList) => [
                                ...criteriaList.slice(0, criteriaIndex),
                                {
                                    ...criteriaList[criteriaIndex],
                                    sort_key: uuidv4(),
                                },
                                ...criteriaList.slice(criteriaIndex),
                            ],
                            groupIndex
                        )
                    }
                    return applyAllCriteriaGroup(state, (groupList) => [
                        ...groupList.slice(0, groupIndex),
                        groupList[groupIndex],
                        ...groupList.slice(groupIndex),
                    ])
                },
                addFilter: (state, { groupIndex }) => {
                    if (groupIndex !== undefined) {
                        return applyAllNestedCriteria(
                            state,
                            (criteriaList) => [...criteriaList, { ...NEW_CRITERIA, sort_key: uuidv4() }],
                            groupIndex
                        )
                    }
                    return applyAllCriteriaGroup(state, (groupList) => [...groupList, NEW_CRITERIA_GROUP])
                },
                removeFilter: (state, { groupIndex, criteriaIndex }) => {
                    if (criteriaIndex !== undefined) {
                        return applyAllNestedCriteria(
                            state,
                            (criteriaList) => [
                                ...criteriaList.slice(0, criteriaIndex),
                                ...criteriaList.slice(criteriaIndex + 1),
                            ],
                            groupIndex
                        )
                    }
                    return applyAllCriteriaGroup(state, (groupList) => [
                        ...groupList.slice(0, groupIndex),
                        ...groupList.slice(groupIndex + 1),
                    ])
                },
                setCriteria: (state, { newCriteria, groupIndex, criteriaIndex }) =>
                    applyAllNestedCriteria(
                        state,
                        (criteriaList) =>
                            criteriaList.map((oldCriteria, criteriaI) =>
                                isCohortCriteriaGroup(oldCriteria)
                                    ? oldCriteria
                                    : criteriaI === criteriaIndex
                                    ? cleanCriteria({ ...oldCriteria, ...newCriteria })
                                    : oldCriteria
                            ),
                        groupIndex
                    ),
            },
        ],
        cohortMissing: [
            false,
            {
                setCohortMissing: () => true,
            },
        ],
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        query: [
            {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    fixedProperties: [
                        { type: PropertyFilterType.Cohort, key: 'id', value: parseInt(String(props.id)) },
                    ],
                },
                full: true,
                showPropertyFilter: false,
                showEventFilter: false,
            } as DataTableNode,
            {
                setQuery: (state, { query }) => (isDataTableNode(query) ? query : state),
            },
        ],
    })),

    forms(({ actions }) => ({
        cohort: {
            defaults: NEW_COHORT,
            errors: ({ id, name, csv, is_static, filters }) => ({
                name: !name ? 'Cohort name cannot be empty' : undefined,
                csv: is_static && id === 'new' && !csv ? 'You need to upload a CSV file' : (null as any),
                filters: {
                    properties: {
                        values: is_static ? undefined : filters.properties.values.map(validateGroup),
                    },
                },
            }),
            submit: (cohort) => {
                if (cohort.id !== 'new') {
                    actions.saveCohort(cohort)
                } else {
                    actions.saveCohort({ ...cohort, _create_in_folder: 'Untitled/Cohorts' })
                }
            },
        },
    })),

    loaders(({ actions, values, key }) => ({
        cohort: [
            NEW_COHORT,
            {
                setCohort: ({ cohort }) => processCohort(cohort),
                fetchCohort: async ({ id }, breakpoint) => {
                    try {
                        const cohort = await api.cohorts.get(id)
                        breakpoint()
                        cohortsModel.actions.updateCohort(cohort)
                        actions.setCohort(cohort)
                        actions.checkIfFinishedCalculating(cohort)
                        return processCohort(cohort)
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to fetch cohort')

                        actions.setCohortMissing()
                        return values.cohort
                    }
                },
                saveCohort: async ({ cohortParams }, breakpoint) => {
                    let cohort = { ...cohortParams }
                    const existingCohort = values.cohort
                    const cohortFormData = createCohortFormData(cohort)

                    try {
                        if (cohort.id !== 'new') {
                            cohort = await api.cohorts.update(cohort.id, cohortFormData as Partial<CohortType>)
                            cohortsModel.actions.updateCohort(cohort)

                            if (cohort.experiment_set && cohort.experiment_set.length > 0) {
                                // someone edited an exposure cohort. Track what kind of updates were made
                                actions.reportExperimentExposureCohortEdited(existingCohort, cohort)
                            }
                        } else {
                            cohort = await api.cohorts.create(cohortFormData as Partial<CohortType>)
                            cohortsModel.actions.cohortCreated(cohort)
                        }
                    } catch (error: any) {
                        breakpoint()
                        lemonToast.error(error.detail || 'Failed to save cohort')
                        return values.cohort
                    }

                    cohort.is_calculating = true // this will ensure there is always a polling period to allow for backend calculation task to run
                    breakpoint()

                    delete cohort['csv']
                    actions.setCohort(cohort)
                    refreshTreeItem('cohort', cohort.id)
                    lemonToast.success('Cohort saved. Please wait up to a few minutes for it to be calculated', {
                        toastId: `cohort-saved-${key}`,
                    })
                    actions.checkIfFinishedCalculating(cohort)
                    return processCohort(cohort)
                },
                onCriteriaChange: ({ newGroup, id }) => {
                    const cohort = { ...values.cohort }
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
                    return processCohort(cohort)
                },
            },
        ],
        duplicatedCohort: [
            null as CohortType | null,
            {
                duplicateCohort: async ({ asStatic }: { asStatic: boolean }, breakpoint) => {
                    let cohort: CohortType
                    try {
                        await breakpoint(200)
                        if (asStatic) {
                            cohort = await api.cohorts.duplicate(values.cohort.id)
                        } else {
                            const data = { ...values.cohort }
                            data.name += ' (dynamic copy)'
                            const cohortFormData = createCohortFormData(data)
                            cohort = await api.cohorts.create(cohortFormData as Partial<CohortType>)
                        }
                        lemonToast.success(
                            'Cohort duplicated. Please wait up to a few minutes for it to be calculated',
                            {
                                toastId: `cohort-duplicated-${cohort.id}`,
                                button: {
                                    label: 'View cohort',
                                    action: () => {
                                        router.actions.push(urls.cohort(cohort.id))
                                    },
                                },
                            }
                        )
                        return cohort
                    } catch (error: any) {
                        lemonToast.error(error.detail || 'Failed to duplicate cohort')
                        return null
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        deleteCohort: () => {
            cohortsModel.findMounted()?.actions.deleteCohort({ id: values.cohort.id, name: values.cohort.name })
            router.actions.push(urls.cohorts())
        },
        submitCohort: () => {
            if (values.cohortHasErrors) {
                lemonToast.error('There was an error submiting this cohort. Make sure the cohort filters are correct.')
            }
        },
        checkIfFinishedCalculating: async ({ cohort }, breakpoint) => {
            if (cohort.is_calculating) {
                actions.setPollTimeout(
                    // eslint-disable-next-line @typescript-eslint/no-misused-promises
                    window.setTimeout(async () => {
                        const newCohort = await api.cohorts.get(cohort.id)
                        breakpoint()
                        actions.checkIfFinishedCalculating(newCohort)
                    }, 1000)
                )
            } else {
                // Only update calculation-related fields, preserve user edits for other fields
                const calculationFields = {
                    is_calculating: cohort.is_calculating,
                    errors_calculating: cohort.errors_calculating,
                    last_calculation: cohort.last_calculation,
                    count: cohort.count,
                }
                actions.setCohort({ ...values.cohort, ...calculationFields })
                cohortsModel.actions.updateCohort(cohort)
                personsLogic.findMounted({ syncWithUrl: true })?.actions.loadCohorts() // To ensure sync on person page
                if (values.pollTimeout) {
                    clearTimeout(values.pollTimeout)
                    actions.setPollTimeout(null)
                }
            }
        },
    })),

    actionToUrl(({ values }) => ({
        saveCohortSuccess: () => urls.cohort(values.cohort.id),
    })),

    afterMount(({ actions, props }) => {
        if (!props.id || props.id === 'new') {
            actions.setCohort(NEW_COHORT)
        } else {
            actions.fetchCohort(props.id)
        }
    }),
    beforeUnmount(({ values }) => {
        if (values.pollTimeout) {
            clearTimeout(values.pollTimeout)
        }
    }),
])
