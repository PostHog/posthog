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
        onCriteriaChange: (newGroup: Partial<CohortGroupType>, id: string) => ({ newGroup, id }),
        fetchCohort: (cohort: CohortType) => ({ cohort }),
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
        setLastSavedAt: (lastSavedAt: string | false) => ({ lastSavedAt }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),
        setSubmitted: (submitted: boolean) => ({ submitted }),
    }),

    reducers: () => ({
        pollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohort: [
            processCohortOnSet(NEW_COHORT),
            {
                setCohort: (_, { cohort }) => {
                    return processCohortOnSet(cohort)
                },
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
        lastSavedAt: [
            false as string | false,
            {
                setLastSavedAt: (_, { lastSavedAt }) => lastSavedAt,
            },
        ],
        submitted: [
            // Indicates the form has been submitted at least once. Used to display validation errors if applicable.
            false,
            {
                setSubmitted: (_, { submitted }) => submitted,
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

    listeners: ({ actions, values, key }) => ({
        saveCohort: async ({ cohortParams, filterParams }, breakpoint) => {
            let cohort = { ...values.cohort, ...cohortParams } as CohortType
            const cohortFormData = new FormData()

            for (const [itemKey, value] of Object.entries(cohort as CohortType)) {
                if (itemKey === 'groups') {
                    if (cohort.is_static) {
                        if (!cohort.csv && cohort.id === 'new') {
                            actions.setSubmitted(true)
                            return
                        }
                    } else {
                        for (const _group of value) {
                            if (_group.matchType === PROPERTY_MATCH_TYPE && !_group.properties?.length) {
                                // Match group should have at least one property
                                actions.setSubmitted(true)
                                return
                            }

                            if (_group.matchType === ENTITY_MATCH_TYPE && !(_group.action_id || _group.event_id)) {
                                // Match group should have an event or action set
                                actions.setSubmitted(true)
                                return
                            }
                        }
                    }

                    const formattedGroups = value.map((group: CohortGroupType) => formatGroupPayload(group))

                    if (!cohort.csv) {
                        cohortFormData.append(itemKey, JSON.stringify(formattedGroups))
                    } else {
                        // If we have a static cohort uploaded by CSV we don't need to send groups
                        cohortFormData.append(itemKey, '[]')
                    }
                } else {
                    cohortFormData.append(itemKey, value)
                }
            }

            try {
                if (cohort.id !== 'new') {
                    cohort = await api.cohorts.update(cohort.id, cohortFormData as Partial<CohortType>, filterParams)
                    cohortsModel.actions.updateCohort(cohort)
                } else {
                    cohort = await api.cohorts.create(cohortFormData as Partial<CohortType>, filterParams)
                    cohortsModel.actions.cohortCreated(cohort)
                }
            } catch (error: any) {
                lemonToast.error(error.detail || 'Failed to save cohort')
                return
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
        },
        deleteCohort: () => {
            cohortsModel.actions.deleteCohort(values.cohort)
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
