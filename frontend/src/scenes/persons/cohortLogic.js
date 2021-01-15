import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { Spin } from 'antd'
import api from 'lib/api'
import { router } from 'kea-router'
import { cohortsModel } from '~/models'

export const cohortLogic = kea({
    key: (props) => props.cohort.id || 'new',
    connect: [cohortsModel],

    actions: () => ({
        saveCohort: (cohort) => ({ cohort }),
        setCohort: (cohort) => ({ cohort }),
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
            props.cohort,
            {
                setCohort: (_, { cohort }) => cohort,
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

    listeners: ({ sharedListeners, actions }) => ({
        saveCohort: async ({ cohort }) => {
            const cohortFormData = new FormData()
            for (const [key, value] of Object.entries(cohort)) {
                if (key === 'groups') {
                    if (!cohort.csv) {
                        cohortFormData.append(key, JSON.stringify(value))
                    } else {
                        // If we have a static cohort uploaded by CSV we don't need to send groups
                        cohortFormData.append(key, '[]')
                    }
                } else {
                    cohortFormData.append(key, value)
                }
            }

            if (cohort.id !== 'new') {
                cohort = await api.update('api/cohort/' + cohort.id, cohortFormData)
                cohortsModel.actions.updateCohort(cohort)
            } else {
                cohort = await api.create('api/cohort', cohortFormData)
                cohortsModel.actions.createCohort(cohort)
            }
            delete cohort['csv']
            actions.setCohort(cohort)
            sharedListeners.pollIsFinished(cohort)
        },
        checkIsFinished: async ({ cohort }) => {
            cohort = await api.get('api/cohort/' + cohort.id)
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
                toast.update(values.toastId, {
                    render: function RenderToast() {
                        return <span data-attr="success-toast">Cohort saved!</span>
                    },
                    autoClose: 5000,
                })
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
