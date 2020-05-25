import React from 'react'
import { kea } from 'kea'
import { toast } from 'react-toastify'
import { Spin } from 'antd'
import api from 'lib/api'
import { router } from 'kea-router'
import { uuid} from 'lib/utils'

export const actionLogic = kea({
    key: props => props.id || 'new',
    actions: () => ({
        saveAction: true,
        setAction: action => ({ action }),
        checkIsFinished: action => ({ action }),
        setToastId: toastId => ({ toastId }),
        setPollTimeout: pollTimeout => ({ pollTimeout }),
        setCreateNew: createNew => ({ createNew })
    }),

    loaders: ({props}) => ({
        action: {
            loadAction: async () => {
                return await api.get(props.apiURL + 'api/action/' + props.id)
            },
        },
    }),

    reducers: () => ({
        pollTimeout: [
            null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        action: [
            null,
            {
                setAction: (_, { action }) => action,
            },
        ],
        toastId: [
            null,
            {
                setToastId: (_, { toastId }) => toastId,
            },
        ],
        createNew: [
            false,
            {
                setCreateNew: (_, {createNew}) => createNew,
            }
        ]
    }),

    listeners: ({ sharedListeners, values, props }) => ({
        saveAction: async () => {
            let action = {...values.action}
            action.steps = action.steps.map(step => {
                if (step.event == '$pageview') step.selection = ['url', 'url_matching']
                if (step.event != '$pageview' && step.event != '$autocapture') step.selection = ['properties']
                if (!step.selection) return step
                let data = {}
                Object.keys(step).map(key => {
                    data[key] = key == 'id' || key == 'event' || step.selection.indexOf(key) > -1 ? step[key] : null
                })
                return data
            })
            if (action.id) {
                action = await api.update(props.apiURL + 'api/action/' + action.id, action)
            } else {
                action = await api.create(props.apiURL + 'api/action', action)
            }
            sharedListeners.pollIsFinished(action)
        },
        checkIsFinished: async ({ action }) => {
            action = await api.get(props.apiURL + 'api/action/' + action.id)
            sharedListeners.pollIsFinished(action)
        },
    }),

    sharedListeners: ({ actions, values, props }) => ({
        pollIsFinished: action => {
            if (action.is_calculating) {
                if (!values.toastId)
                    actions.setToastId(
                        toast(
                            <span>
                                <Spin /> Calculating action "{action.name}"
                            </span>,
                            {
                                autoClose: false,
                            }
                        )
                    )
                actions.setPollTimeout(setTimeout(() => actions.checkIsFinished(action), 1000))
            } else {
                toast.update(values.toastId, {
                    render: 'Action saved!',
                    autoClose: 5000,
                })
                props.onSave(action.id, values.createNew)
                actions.setToastId(null)
            }
        },
    }),

    events: ({ values, actions, props }) => ({
        afterMount: async () => {
            if (props.id) {
                const action = await api.get('api/action/' + props.id + '/' + props.params)
                return actions.setAction(action)
            }
            actions.setAction(
                { name: '', steps: [{ isNew: uuid() }] }
            )
        },
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),
})
