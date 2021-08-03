// DEPRECATED in favor of CohortV2/cohortLogic.tsx
import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { Spin } from 'antd'
import api from 'lib/api'
import { router } from 'kea-router'
import { cohortsModel } from '~/models/cohortsModel'
import { Link } from 'lib/components/Link'
import { ENTITY_MATCH_TYPE, PROPERTY_MATCH_TYPE } from 'lib/constants'

function formatGroupPayload(group) {
    return { ...group, id: undefined, matchType: undefined }
}

function addLocalCohortGroupId(group) {
    return {
        id: Math.random().toString().substr(2, 5),
        matchType: determineMatchType(group),
        ...group,
    }
}

function determineMatchType(group) {
    if (group.action_id || group.event_id) {
        return ENTITY_MATCH_TYPE
    } else {
        return PROPERTY_MATCH_TYPE
    }
}

function processCohortOnSet(cohort) {
    if (cohort.groups) {
        cohort.groups = cohort.groups.map((group) => addLocalCohortGroupId(group))
    }
    return cohort
}

export const cohortLogic = kea({
    key: (props) => props.cohort.id || 'new',
    connect: [cohortsModel],

    actions: () => ({
        saveCohort: (cohortParams = {}, filterParams = null) => ({ cohortParams, filterParams }),
        setCohort: (cohort) => ({ cohort }),
        updateCohortGroups: (groups) => ({ groups }),
        checkIsFinished: (cohort) => ({ cohort }),
        setToastId: (toastId) => ({ toastId }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setLastSavedAt: (lastSavedAt) => ({ lastSavedAt }),
    }),

    reducers: ({ props }) => ({
        pollTimeout: [
            null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohort: [
            processCohortOnSet(props.cohort),
            {
                setCohort: (s, { cohort }) => processCohortOnSet(cohort),
                updateCohortGroups: (state, { groups }) => {
                    return processCohortOnSet({ ...state, groups })
                },
            },
        ],
        toastId: [
            null,
            {
                setToastId: (_, { toastId }) => toastId,
            },
        ],
        lastSavedAt: [
            false,
            {
                setLastSavedAt: (_, { lastSavedAt }) => lastSavedAt,
            },
        ],
    }),

    selectors: () => ({
        isNewCohort: [
            (selectors) => [selectors.cohort],
            (cohort) => cohort.id === 'new' || cohort.id === 'personsModalNew',
        ],
    }),

    listeners: ({ sharedListeners, actions, values }) => ({
        saveCohort: async ({ cohortParams, filterParams }, breakpoint) => {
            let cohort = { ...values.cohort, ...cohortParams }
            const cohortFormData = new FormData()
            for (const [key, value] of Object.entries(cohort)) {
                if (key === 'groups') {
                    const formattedGroups = value.map((group) => formatGroupPayload(group))
                    if (!cohort.csv) {
                        cohortFormData.append(key, JSON.stringify(formattedGroups))
                    } else {
                        // If we have a static cohort uploaded by CSV we don't need to send groups
                        cohortFormData.append(key, '[]')
                    }
                } else {
                    cohortFormData.append(key, value)
                }
            }
            if (cohort.id === 'new' || cohort.id === 'personsModalNew') {
                cohort = await api.create('api/cohort' + (filterParams ? '?' + filterParams : ''), cohortFormData)
                cohortsModel.actions.createCohort(cohort)
            } else {
                cohort = await api.update(
                    'api/cohort/' + cohort.id + (filterParams ? '?' + filterParams : ''),
                    cohortFormData
                )
                cohortsModel.actions.updateCohort(cohort)
            }
            cohort.is_calculating = true // this will ensure there is always a polling period to allow for backend calculation task to run
            breakpoint()
            delete cohort['csv']
            actions.setCohort(cohort)
            sharedListeners.pollIsFinished(cohort)
        },
        checkIsFinished: async ({ cohort }, breakpoint) => {
            cohort = await api.get('api/cohort/' + cohort.id)
            breakpoint()
            sharedListeners.pollIsFinished(cohort)
        },
    }),

    sharedListeners: ({ actions, values }) => ({
        pollIsFinished: (cohort) => {
            if (cohort.is_calculating) {
                if (!values.toastId) {
                    actions.setToastId(
                        toast(
                            <span>
                                <Spin /> Calculating cohort "{cohort.name}"
                            </span>,
                            {
                                autoClose: false,
                            }
                        )
                    )
                }
                actions.setPollTimeout(setTimeout(() => actions.checkIsFinished(cohort), 1000))
            } else {
                if (values.toastId) {
                    toast.update(values.toastId, {
                        render: function RenderToast() {
                            return (
                                <div data-attr="success-toast">
                                    Cohort Saved&nbsp;
                                    <Link to={`/cohorts/${cohort.id}`}>Click here to see it.</Link>
                                </div>
                            )
                        },
                        autoClose: 5000,
                    })
                } else {
                    actions.setToastId(
                        toast(
                            <div data-attr="success-toast">
                                Cohort Saved&nbsp;
                                <Link to={`/cohorts/${cohort.id}`}>Click here to see it.</Link>
                            </div>,
                            {
                                autoClose: false,
                            }
                        )
                    )
                }
                actions.setLastSavedAt(new Date().toISOString())
                actions.setCohort(cohort)
                cohortsModel.actions.updateCohort(cohort)
                actions.setToastId(null)
            }
        },
    }),

    events: ({ values, actions, props }) => ({
        afterMount: async () => {
            if (!props.cohort.id) {
                actions.setCohort({ groups: router.values.location.pathname.indexOf('cohorts/new') > -1 ? [{}] : [] })
            }
        },
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),
})
