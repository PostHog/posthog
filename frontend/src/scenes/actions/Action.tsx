import React from 'react'
import { ActionEdit } from './ActionEdit'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { EventsTable } from 'scenes/events'
import { urls } from 'scenes/urls'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { ActionType } from '~/types'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { actionLogic, ActionLogicProps } from 'scenes/actions/actionLogic'

export const scene: SceneExport = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: parseInt(id), onComplete: () => {} }),
}

export function Action({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const fixedFilters = { action_id: id }

    const { push } = useActions(router)
    const { fetchEvents } = useActions(
        eventsTableLogic({ fixedFilters, sceneUrl: id ? urls.action(id) : urls.actions() })
    )
    const { action, isComplete } = useValues(actionLogic({ id, onComplete: fetchEvents }))
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
                    <div className="flex-center">
                        <Spinner style={{ marginRight: 12 }} />
                        Calculating action, please hold on.
                    </div>
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
                    {id && (
                        <EventsTable fixedFilters={fixedFilters} filtersEnabled={false} sceneUrl={urls.action(id)} />
                    )}
                </div>
            )}
        </div>
    )
}
