import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { Spin } from 'antd'
import api from 'lib/api'

import { cohortsModel } from '~/models/cohortsModel'

export const cohortLogic = kea({
    actions: () => ({
        saveCohort: cohort => ({ cohort }),
        setCohort: cohort => ({ cohort }),
        checkIsFinished: cohort => ({ cohort }),
        setToastId: toastId => ({ toastId }),
        setPollTimeout: pollTimeout => ({ pollTimeout }),
    }),

    loaders: () => ({
        personProperties: {
            loadPersonProperties: async () => {
                const properties = await api.get('api/person/properties')
                return properties.map(property => ({
                    label: property.name,
                    value: property.name,
                }))
            },
        },
    }),

    reducers: ({ props }) => ({
        pollTimeout: [
            null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        cohort: [
            null,
            {
                setCohort: (_, { cohort }) => cohort,
                [cohortsModel.actions.loadCohortsSuccess]: (_, { cohorts }) => {
                    if (!props.id) return values.cohort
                    return cohorts.filter(cohort => cohort.id === parseInt(props.id))[0]
                },
            },
        ],
        toastId: [
            null,
            {
                setToastId: (_, { toastId }) => toastId,
            },
        ],
    }),

    listeners: ({ sharedListeners }) => ({
        saveCohort: async ({ cohort }) => {
            if (cohort.id) {
                cohort = await api.update('api/cohort/' + cohort.id, cohort)
            } else {
                cohort = await api.update('api/cohort', cohort)
            }
            sharedListeners.pollIsFinished(cohort)
        },
        checkIsFinished: async ({ cohort }) => {
            cohort = await api.get('api/cohort/' + cohort.id)
            sharedListeners.pollIsFinished(cohort)
        },
    }),

    sharedListeners: ({ actions, values, props }) => ({
        pollIsFinished: cohort => {
            if (cohort.is_calculating) {
                if (!values.toastId)
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
                actions.setPollTimeout(setTimeout(() => actions.checkIsFinished(cohort), 1000))
            } else {
                toast.update(values.toastId, {
                    render: 'Cohort saved!',
                    autoClose: 5000,
                })
                props.onChange(cohort.id)
                actions.setToastId(null)
            }
        },
    }),

    events: ({ values, actions, props }) => ({
        afterMount: () => {
            if (props.id && cohortsModel.values.cohorts)
                return actions.setCohort(cohortsModel.values.cohorts.filter(cohort => cohort.id === props.id)[0])
            actions.setCohort({ groups: [] })
        },
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),
})
