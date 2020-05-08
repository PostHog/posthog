import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { Spin } from 'antd'
import api from 'lib/api'
import { router } from 'kea-router'

export const cohortLogic = kea({
    key: props => props.id || 'new',
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

    reducers: ({ props, values }) => ({
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
                cohort = await api.create('api/cohort', cohort)
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
        afterMount: async () => {
            if (props.id) {
                const cohort = await api.get('api/cohort/' + props.id)
                return actions.setCohort(cohort)
            }
            actions.setCohort({ groups: router.values.location.pathname.indexOf('new_cohort') > -1 ? [{}] : [] })
        },
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),
})
