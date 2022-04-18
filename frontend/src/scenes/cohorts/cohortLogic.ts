import { kea } from 'kea'
import api from 'lib/api'
import { cohortsModel } from '~/models/cohortsModel'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'
import { cohortLogicType } from './cohortLogicType'
import { Breadcrumb, CohortGroupType, CohortType, MatchType } from '~/types'
import { convertPropertyGroupToProperties } from 'lib/utils'
import { personsLogic } from 'scenes/persons/personsLogic'
import { lemonToast } from 'lib/components/lemonToast'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'

export const NEW_COHORT: CohortType = {
    id: 'new',
    groups: [
        {
            id: Math.random().toString().substr(2, 5),
            matchType: PROPERTY_MATCH_TYPE,
            properties: [],
        },
    ],
}

function formatGroupPayload(group: CohortGroupType): Partial<CohortGroupType> {
    return { ...group, id: undefined, matchType: undefined }
}

function addLocalCohortGroupId(group: Partial<CohortGroupType>): CohortGroupType {
    return {
        matchType: determineMatchType(group),
        id: Math.random().toString().substr(2, 5),
        ...group,
    }
}

function determineMatchType(group: Partial<CohortGroupType>): MatchType {
    if (group.action_id || group.event_id) {
        return ENTITY_MATCH_TYPE
    } else {
        return PROPERTY_MATCH_TYPE
    }
}

function processCohortOnSet(cohort: CohortType): CohortType {
    if (cohort.groups) {
        cohort.groups = cohort.groups.map((group) => addLocalCohortGroupId(group))
        cohort.groups = cohort.groups.map((group) => {
            if (group.properties) {
                return {
                    ...group,
                    properties: convertPropertyGroupToProperties(group.properties),
                }
            }
            return group
        })
    }

    return cohort
}

export interface CohortLogicProps {
    pageKey: string | number
    id?: CohortType['id']
}

export const cohortLogic = kea<cohortLogicType<CohortLogicProps>>({
    props: {} as CohortLogicProps,
    key: (props) => (props.id === 'new' ? `new-${props.pageKey}` : props.id) ?? 'new',
    path: (key) => ['scenes', 'cohorts', 'cohortLogic', key],
    connect: [cohortsModel],

    actions: () => ({
        saveCohort: (cohortParams = {}, filterParams = null) => ({ cohortParams, filterParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        deleteCohort: true,
        cancelCohort: true,
        onCriteriaChange: (newGroup: Partial<CohortGroupType>, id: string) => ({ newGroup, id }),
        fetchCohort: (cohort: CohortType) => ({ cohort }),
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
        setLastSavedAt: (lastSavedAt: string | false) => ({ lastSavedAt }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),
        setSubmitted: (submitted: boolean) => ({ submitted }),
    }),

    reducers: () => ({
        cohort: [
            processCohortOnSet(NEW_COHORT) as CohortType,
            {
                onCriteriaChange: (state, { newGroup, id }) => {
                    const cohort = { ...state }
                    const index = cohort.groups.findIndex((group: CohortGroupType) => group.id === id)
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
            },
        ],
        pollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        lastSavedAt: [
            false as string | false,
            {
                setLastSavedAt: (_, { lastSavedAt }) => lastSavedAt,
            },
        ],
    }),

    forms: ({ actions }) => ({
        cohort: {
            defaults: processCohortOnSet(NEW_COHORT),
            validator: ({ name, csv, is_static, id, groups }) => ({
                name: !name ? 'You need to set a name' : undefined,
                csv: {
                    uid: id === 'new' && is_static && !csv ? 'You need to upload a CSV file' : undefined,
                },
                groups: groups?.map(({ matchType, properties, action_id, event_id }) => {
                    if (
                        (matchType === ENTITY_MATCH_TYPE && !properties?.length) ||
                        (matchType === PROPERTY_MATCH_TYPE && !(action_id || event_id))
                    ) {
                        return { id: 'This matching group is invalid' }
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
            processCohortOnSet(NEW_COHORT) as CohortType,
            {
                setCohort: ({ cohort }) => {
                    return processCohortOnSet(cohort)
                },
                saveCohort: async ({ cohortParams, filterParams }, breakpoint) => {
                    let cohort = { ...values.cohort, ...cohortParams } as CohortType

                    const cohortFormData = {
                        ...cohort,
                        groups: cohort.groups.map((group: CohortGroupType) => formatGroupPayload(group)),
                    }

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

                    actions.setSubmitted(false)
                    cohort.is_calculating = true // this will ensure there is always a polling period to allow for backend calculation task to run
                    breakpoint()
                    delete cohort['csv']
                    actions.setCohort(cohort)
                    lemonToast.success('Cohort saved. Please wait up to a few minutes for it to be calculated', {
                        toastId: `cohort-saved-${key}`,
                    })
                    actions.checkIfFinishedCalculating(cohort)
                    return cohort
                },
            },
        ],
    }),

    selectors: {
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
            cohortsModel.actions.deleteCohort(values.cohort)
            router.actions.push(urls.cohorts())
        },
        cancelCohort: () => {
            router.actions.push(urls.cohorts())
        },
        fetchCohort: async ({ cohort }, breakpoint) => {
            cohort = await api.cohorts.get(cohort.id)
            breakpoint()
            actions.checkIfFinishedCalculating(cohort)
        },
        checkIfFinishedCalculating: async ({ cohort }, breakpoint) => {
            breakpoint()
            if (cohort.is_calculating) {
                actions.setPollTimeout(setTimeout(() => actions.fetchCohort(cohort), 1000))
            } else {
                actions.setLastSavedAt(new Date().toISOString())
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

    events: ({ values, actions, props }) => ({
        afterMount: async () => {
            if (!props.id || props.id === 'new') {
                actions.setCohort(NEW_COHORT)
            } else {
                const cohort = await api.cohorts.get(Number(props.id))
                actions.setCohort(cohort)
            }
        },
        beforeUnmount: () => {
            if (values.pollTimeout) {
                clearTimeout(values.pollTimeout)
            }
        },
    }),
})
