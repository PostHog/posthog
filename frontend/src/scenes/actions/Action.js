import React from 'react'
import { Events } from '../events/Events'
import { ActionEdit } from './ActionEdit'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { userLogic } from 'scenes/userLogic'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import api from 'lib/api'
import { kea } from 'kea'
import { Spin } from 'antd'
import { hot } from 'react-hot-loader/root'

let actionLogic = kea({
    key: props => props.id || 'new',
    actions: () => ({
        checkIsFinished: action => ({ action }),
        setPollTimeout: pollTimeout => ({ pollTimeout }),
        setIsComplete: isComplete => ({ isComplete }),
    }),
    reducers: () => ({
        pollTimeout: [
            null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        isComplete: [
            false,
            {
                setIsComplete: (_, { isComplete }) => isComplete,
            },
        ],
    }),
    loaders: ({ actions, props }) => ({
        action: {
            loadAction: async () => {
                actions.setIsComplete(false)
                let action = await api.get('api/action/' + props.id)
                actions.checkIsFinished(action)
                return action
            },
        },
    }),
    listeners: ({ actions, props, values }) => ({
        checkIsFinished: ({ action }) => {
            if (action.is_calculating) {
                actions.setPollTimeout(setTimeout(() => actions.loadAction(), 1000))
            } else {
                props.onComplete()
                actions.setIsComplete(new Date())
                clearTimeout(values.pollTimeout)
            }
        },
    }),
    events: ({ values, actions, props }) => ({
        afterMount: async () => {
            if (props.id) {
                actions.loadAction()
            }
        },
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),
})

export const Action = hot(_Action)
function _Action({ id }) {
    const fixedFilters = { action_id: id }

    const { push } = useActions(router)
    const { user } = useValues(userLogic)
    const { fetchEvents } = useActions(eventsTableLogic({ fixedFilters }))
    const { isComplete } = useValues(actionLogic({ id, onComplete: fetchEvents }))
    const { loadAction } = useActions(actionLogic({ id, onComplete: fetchEvents }))

    return (
        <div>
            <h1>{id ? 'Edit action' : 'New Action'}</h1>
            <ActionEdit
                apiURL=""
                actionId={id}
                user={user}
                onSave={action => {
                    if (!id) {
                        push(`/action/${action.id}`)
                    }
                    loadAction()
                }}
            />
            {id && !isComplete && (
                <div style={{ marginBottom: '10rem' }}>
                    <h1 className="page-header">Events</h1>
                    <Spin style={{ marginRight: 12 }} />
                    Calculating action, please hold on.
                </div>
            )}
            {isComplete && <Events key={isComplete} fixedFilters={fixedFilters} filtersEnabled={false} />}
        </div>
    )
}
