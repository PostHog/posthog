import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import api from 'lib/api'
import { cohortsModel } from '~/models/cohortsModel'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'

import { cohortLogicType } from './cohortLogicType'
import { CohortGroupType, CohortType, MatchType } from '~/types'
import { errorToast } from 'lib/utils'

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
    }
    return cohort
}

export const cohortLogic = kea<cohortLogicType>({
    props: {} as {
        cohort: CohortType
    },
    key: (props) => props.cohort.id || 'new',
    connect: [cohortsModel],

    actions: () => ({
        saveCohort: (cohortParams = {}, filterParams = null) => ({ cohortParams, filterParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        onCriteriaChange: (newGroup: Partial<CohortGroupType>, id: string) => ({ newGroup, id }),
        fetchCohort: (cohort: CohortType) => ({ cohort }),
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
        setLastSavedAt: (lastSavedAt: string | false) => ({ lastSavedAt }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),
        setSubmitted: (submitted: boolean) => ({ submitted }),
    }),

    reducers: ({ props }) => ({
        pollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohort: [
            processCohortOnSet(props.cohort),
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
                            matchType: ENTITY_MATCH_TYPE, // default
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
            } catch (error) {
                errorToast(
                    'Error saving your cohort',
                    'Attempting to save this cohort returned an error:',
                    error.status !== 0
                        ? error.detail
                        : "Check your internet connection and make sure you don't have an extension blocking our requests.",
                    error.code
                )
                return
            }

            actions.setSubmitted(false)
            cohort.is_calculating = true // this will ensure there is always a polling period to allow for backend calculation task to run
            breakpoint()
            delete cohort['csv']
            actions.setCohort(cohort)
            toast.success(
                <div data-attr="success-toast">
                    <h1>Cohort saved successfully!</h1>
                    <p>Please wait up to a few minutes for the cohort to be calculated.</p>
                </div>,
                {
                    toastId: `cohort-saved-${key}`,
                }
            )
            actions.checkIfFinishedCalculating(cohort)
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
                if (values.pollTimeout) {
                    clearTimeout(values.pollTimeout)
                    actions.setPollTimeout(null)
                }
            }
        },
    }),

    events: ({ values, actions, props }) => ({
        afterMount: async () => {
            if (!props.cohort.id) {
                actions.setCohort({ groups: [], id: 'new' })
            }
        },
        beforeUnmount: () => {
            if (values.pollTimeout) {
                clearTimeout(values.pollTimeout)
            }
        },
    }),
})
