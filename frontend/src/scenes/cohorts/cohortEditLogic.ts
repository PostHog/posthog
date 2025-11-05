import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import api from 'lib/api'
import { ENTITY_MATCH_TYPE } from 'lib/constants'
import { scrollToFormError } from 'lib/forms/scrollToFormError'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { NEW_COHORT, NEW_CRITERIA, NEW_CRITERIA_GROUP } from 'scenes/cohorts/CohortFilters/constants'
import {
    applyAllCriteriaGroup,
    applyAllNestedCriteria,
    cleanCriteria,
    createCohortDataNodeLogicKey,
    createCohortFormData,
    isCohortCriteriaGroup,
    validateGroup,
} from 'scenes/cohorts/cohortUtils'
import { personsLogic } from 'scenes/persons/personsLogic'
import { urls } from 'scenes/urls'

import { refreshTreeItem } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { cohortsModel, processCohort } from '~/models/cohortsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
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
    tabId?: string
}

export const cohortEditLogic = kea<cohortEditLogicType>([
    props({} as CohortLogicProps),
    key((props) => {
        if (props.id === 'new' || !props.id) {
            if (props.tabId == null) {
                return 'new'
            }
            return `new-${props.tabId}`
        }
        if (props.tabId == null) {
            return props.id
        }
        return `${props.id}-${props.tabId}`
    }),
    path(['scenes', 'cohorts', 'cohortLogicEdit']),
    connect(() => ({
        actions: [eventUsageLogic, ['reportExperimentExposureCohortEdited']],
        logic: [cohortsModel],
    })),

    actions({
        saveCohort: (cohortParams = {}) => ({ cohortParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: true,
        restoreCohort: true,
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
        updateCohortCount: true,
        setCreationPersonQuery: (query: Node) => ({ query }),
        addPersonToCreateStaticCohort: (personId: string) => ({ personId }),
        removePersonFromCreateStaticCohort: (personId: string) => ({ personId }),
        removePersonFromCohort: (personId: string) => ({ personId }),
        resetPersonsToCreateStaticCohort: true,
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
                        {
                            ...groupList[groupIndex],
                            sort_key: uuidv4(),
                        },
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
                    return applyAllCriteriaGroup(state, (groupList) => [
                        ...groupList,
                        { ...NEW_CRITERIA_GROUP, sort_key: uuidv4() },
                    ])
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
                setCohort: (state, { cohort }) => ({
                    ...state,
                    source: {
                        ...state.source,
                        select: cohort.is_static
                            ? ['person_display_name -- Person', 'id', 'created_at', 'person.$delete']
                            : ['person_display_name -- Person', 'id', 'created_at'],
                    },
                }),
            },
        ],
        creationPersonQuery: [
            {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.ActorsQuery,
                    fixedProperties: [],
                    select: ['id', 'person_display_name -- Person'],
                },
                showPropertyFilter: false,
                showEventFilter: false,
                showExport: false,
                showSearch: true,
                showActions: false,
                showElapsedTime: false,
                showTimings: false,
            } as DataTableNode,
            {
                setCreationPersonQuery: (state, { query }) => (isDataTableNode(query) ? query : state),
            },
        ],
        personsToCreateStaticCohort: [
            {} as Record<string, boolean>,
            {
                addPersonToCreateStaticCohort: (state, { personId }) => ({
                    ...state,
                    [personId]: true,
                }),
                removePersonFromCreateStaticCohort: (state, { personId }) => {
                    const newState = { ...state }
                    delete newState[personId]
                    return newState
                },
                resetPersonsToCreateStaticCohort: () => ({}),
            },
        ],
    })),

    selectors({
        canRemovePersonFromCohort: [
            (s) => [s.cohort],
            (cohort: CohortType) => {
                return cohort.is_static && typeof cohort.id === 'number'
            },
        ],
    }),

    forms(({ actions, values }) => ({
        cohort: {
            defaults: NEW_COHORT,
            errors: ({ name, is_static, filters }) => ({
                name: !name ? 'Cohort name cannot be empty' : undefined,
                csv: undefined,
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
                    const personIds = Object.keys(values.personsToCreateStaticCohort)
                    if (cohort.is_static && cohort.csv == null && personIds.length === 0) {
                        lemonToast.error('You need to upload a csv file or add a person manually.')
                        return
                    }
                    actions.saveCohort({
                        ...cohort,
                        _create_in_folder: 'Unfiled/Cohorts',
                        _create_static_person_ids: personIds.length > 0 ? personIds : undefined,
                    })
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
                restoreCohort: async () => {
                    try {
                        const restoredCohort = await api.cohorts.update(values.cohort.id, {
                            deleted: false,
                        })
                        actions.setCohort(restoredCohort)
                        lemonToast.success('Cohort restored successfully.')
                        return restoredCohort
                    } catch (error) {
                        lemonToast.error(`Failed to restore cohort: '${error}'`)
                        return values.cohort
                    }
                },
                saveCohort: async ({ cohortParams }, breakpoint) => {
                    const existingCohort = values.cohort
                    let cohort = { ...existingCohort, ...cohortParams }
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

                        // Only capture exception if we don't have proper error details
                        // This indicates an unexpected failure (network, timeout, etc.)
                        if (!error.detail) {
                            console.error('Cohort creation failed unexpectedly:', error, {
                                cohort_name: cohort.name,
                                operation_type: cohort.id === 'new' ? 'create' : 'update',
                                is_static: cohort.is_static,
                            })
                            posthog.captureException(error, {
                                cohort_operation: 'Cohort creation failed unexpectedly',
                                // Cohort context (most valuable)
                                cohort_name: cohort.name,
                                is_static: cohort.is_static,
                                operation_type: cohort.id === 'new' ? 'create' : 'update',
                                has_csv: !!cohortFormData.get?.('csv'),
                                file_size: (() => {
                                    const csvFile = cohortFormData.get?.('csv')
                                    return csvFile instanceof File ? csvFile.size : undefined
                                })(),

                                // Error context
                                error_status: error.status,
                                error_status_text: error.statusText,
                                error_message: error.message,
                                error_name: error.name,
                                error_type: typeof error,

                                // Browser context
                                user_agent: navigator.userAgent.substring(0, 100),
                                is_online: navigator.onLine,

                                // Request context
                                timestamp: new Date().toISOString(),
                            })
                        }

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
                    if (cohort.id !== 'new') {
                        const mountedDataNodeLogic = dataNodeLogic.findMounted({
                            key: createCohortDataNodeLogicKey(cohort.id),
                        })
                        mountedDataNodeLogic?.actions.loadData('force_blocking')
                    }
                    if (existingCohort.id === 'new') {
                        router.actions.push(urls.cohort(cohort.id))
                        if (existingCohort.is_static) {
                            actions.resetPersonsToCreateStaticCohort()
                        }
                        return { ...NEW_COHORT }
                    }
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
                updateCohortCount: async () => {
                    const cohort = await api.cohorts.get(values.cohort.id)
                    return {
                        ...values.cohort,
                        count: cohort.count,
                    }
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

        removePersonFromCohort: [
            null as any,
            {
                removePersonFromCohort: async ({ personId }) => {
                    if (!values.cohort.id || values.cohort.id === 'new') {
                        throw new Error('Cannot remove person from unsaved cohort')
                    }

                    try {
                        await api.cohorts.removePersonFromCohort(values.cohort.id, personId)
                        lemonToast.success('Person removed from cohort')
                    } catch (error: any) {
                        throw error
                    }
                    // Refresh cohort data + count
                    const dataLogic = dataNodeLogic.findMounted({
                        key: createCohortDataNodeLogicKey(values.cohort.id),
                    })
                    if (dataLogic) {
                        dataLogic.actions.loadData('force_blocking')
                    }
                    actions.updateCohortCount()
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        deleteCohort: () => {
            cohortsModel.actions.deleteCohort({ id: values.cohort.id, name: values.cohort.name })
        },
        submitCohortFailure: () => {
            scrollToFormError({
                extraErrorSelectors: ['.CohortCriteriaRow__Criteria--error'],
                fallbackErrorMessage:
                    'There was an error submitting this cohort. Make sure the cohort filters are correct.',
            })
        },
        checkIfFinishedCalculating: async ({ cohort }, breakpoint) => {
            if (cohort.is_calculating) {
                actions.setPollTimeout(
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
