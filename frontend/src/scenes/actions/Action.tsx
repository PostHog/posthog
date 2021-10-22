import React from 'react'
import { ActionEdit } from './ActionEdit'
import { kea, useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import api from 'lib/api'
import { Spin } from 'antd'
import { EventsTable } from 'scenes/events'
import dayjs from 'dayjs'
import { urls } from 'scenes/urls'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { teamLogic } from '../teamLogic'
import { ActionType } from '../../types'

import { actionLogicType } from './ActionType'
interface ActionLogicProps {
    id?: ActionType['id']
    onComplete: () => void
}

const actionLogic = kea<actionLogicType<ActionLogicProps>>({
    props: {} as ActionLogicProps,
    key: (props) => props.id || 'new',
    actions: () => ({
        checkIsFinished: (action) => ({ action }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setIsComplete: (isComplete) => ({ isComplete }),
    }),
    reducers: () => ({
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        isComplete: [
            false as boolean,
            {
                setIsComplete: (_, { isComplete }) => isComplete,
            },
        ],
    }),
    loaders: ({ actions, props }) => ({
        action: {
            loadAction: async () => {
                actions.setIsComplete(false)
                const action = await api.get(`api/projects/${teamLogic.values.currentTeamId}/actions/${props.id}`)
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
                values.pollTimeout && clearTimeout(values.pollTimeout)
            }
        },
    }),
    events: ({ values, actions, props }) => ({
        afterMount: () => {
            props.id && actions.loadAction()
        },
        beforeUnmount: () => {
            values.pollTimeout && clearTimeout(values.pollTimeout)
        },
    }),
})

export function Action({ id }: { id: ActionType['id'] }): JSX.Element {
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
                    id={id}
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
                    {id && <EventsTable fixedFilters={fixedFilters} filtersEnabled={false} />}
                </div>
            )}
        </div>
    )
}
