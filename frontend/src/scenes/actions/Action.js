import React from 'react'
import { ActionEdit } from './ActionEdit'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import api from 'lib/api'
import { kea } from 'kea'
import { Spin } from 'antd'
import { EventsTable } from 'scenes/events'
import dayjs from 'dayjs'
import { urls } from 'scenes/urls'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

const actionLogic = kea({
    key: (props) => props.id || 'new',
    actions: () => ({
        checkIsFinished: (action) => ({ action }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setIsComplete: (isComplete) => ({ isComplete }),
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

export function Action({ id }) {
    const fixedFilters = { action_id: id }

    const { push } = useActions(router)
    const { fetchEvents } = useActions(eventsTableLogic({ fixedFilters }))
    const { isComplete, action } = useValues(actionLogic({ id, onComplete: fetchEvents }))
    const { loadAction } = useActions(actionLogic({ id, onComplete: fetchEvents }))
    const { preflight } = useValues(preflightLogic)
    const isClickHouseEnabled = !!preflight?.is_clickhouse_enabled

    return (
        <div>
            {(!id || action) && (
                <ActionEdit
                    apiURL=""
                    actionId={id}
                    action={action}
                    onSave={(savedAction) => {
                        if (!id) {
                            push(urls.action(savedAction.id))
                        }
                        loadAction()
                    }}
                />
            )}
            {id && !isComplete && (
                <div style={{ marginBottom: '10rem' }}>
                    <h2 className="subtitle">Events</h2>
                    <Spin style={{ marginRight: 12 }} />
                    Calculating action, please hold on.
                </div>
            )}
            {isComplete && (
                <div style={{ marginTop: 86 }}>
                    {!isClickHouseEnabled ? (
                        <>
                            <h2 className="subtitle">Event List</h2>
                            <p className="text-muted">
                                List of the events that match this action.{' '}
                                {action && (
                                    <>
                                        This list was{' '}
                                        <b>
                                            calculated{' '}
                                            {action.last_calculated_at
                                                ? dayjs(action.last_calculated_at).fromNow()
                                                : 'a while ago'}
                                        </b>
                                    </>
                                )}
                            </p>{' '}
                        </>
                    ) : null}
                    {id && <EventsTable key={isComplete} fixedFilters={fixedFilters} filtersEnabled={false} />}
                </div>
            )}
        </div>
    )
}
