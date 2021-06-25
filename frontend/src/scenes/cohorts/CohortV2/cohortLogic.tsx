import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import api from 'lib/api'
import { cohortsModel } from '~/models/cohortsModel'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'

import { cohortLogicType } from './cohortLogicType'
import { CohortGroupType, CohortType, MatchType } from '~/types'

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
    props: {} as { cohort: CohortType },
    key: (props) => props.cohort.id || 'new',
    connect: [cohortsModel],

    actions: () => ({
        saveCohort: (cohortParams = {}, filterParams = null) => ({ cohortParams, filterParams }),
        setCohort: (cohort: CohortType) => ({ cohort }),
        fetchCohort: (cohort: CohortType) => ({ cohort }),
        setPollTimeout: (pollTimeout: NodeJS.Timeout | null) => ({ pollTimeout }),
        setLastSavedAt: (lastSavedAt: string | false) => ({ lastSavedAt }),
        checkIfFinishedCalculating: (cohort: CohortType) => ({ cohort }),
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
                setCohort: (_, { cohort }) => processCohortOnSet(cohort),
            },
        ],
        lastSavedAt: [
            false as string | false,
            {
                setLastSavedAt: (_, { lastSavedAt }) => lastSavedAt,
            },
        ],
    }),

    listeners: ({ actions, values, key }) => ({
        saveCohort: async ({ cohortParams, filterParams }, breakpoint) => {
            let cohort = { ...values.cohort, ...cohortParams } as CohortType
            const cohortFormData = new FormData()
            for (const [itemKey, value] of Object.entries(cohort as CohortType)) {
                if (itemKey === 'groups') {
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

            if (cohort.id !== 'new') {
                cohort = await api.update(
                    'api/cohort/' + cohort.id + (filterParams ? '?' + filterParams : ''),
                    cohortFormData
                )
                cohortsModel.actions.updateCohort(cohort)
            } else {
                cohort = await api.create('api/cohort' + (filterParams ? '?' + filterParams : ''), cohortFormData)
                cohortsModel.actions.createCohort(cohort)
            }
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
            cohort = await api.get('api/cohort/' + cohort.id)
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
                // TODO: router.values.location.pathname.indexOf('cohorts/new') > -1 ? [{}] :
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
