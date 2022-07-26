import React from 'react'
import { ActionEdit } from './ActionEdit'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { EventsTable } from 'scenes/events'
import { urls } from 'scenes/urls'
import { ActionType } from '~/types'
import { dayjs } from 'lib/dayjs'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { actionLogic, ActionLogicProps } from 'scenes/actions/actionLogic'

export const scene: SceneExport = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: parseInt(id) }),
}

// Action has been renamed to Event and Event to Raw Event in the UI (not code) as per #10139
export function Action({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const fixedFilters = { action_id: id }

    const { push } = useActions(router)

    const { action, isComplete, shouldSimplifyActions } = useValues(actionLogic)
    const { loadAction } = useActions(actionLogic)

    return (
        <>
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
            {id &&
                (isComplete ? (
                    <div>
                        <h2 className="subtitle">Matching events</h2>
                        <p>
                            This is the list of <strong>recent</strong> raw events that match this{' '}
                            {shouldSimplifyActions ? 'event' : 'action'}.
                            {action?.last_calculated_at ? (
                                <>
                                    {' '}
                                    Last calculated: <b>{dayjs(action.last_calculated_at).fromNow()}</b>.
                                </>
                            ) : (
                                ''
                            )}
                        </p>
                        <EventsTable
                            fixedFilters={fixedFilters}
                            sceneUrl={urls.action(id)}
                            fetchMonths={3}
                            pageKey={`action-${id}-${JSON.stringify(fixedFilters)}`}
                            showEventFilter={false}
                        />
                    </div>
                ) : (
                    <div>
                        <h2 className="subtitle">Matching events</h2>
                        <div className="flex items-center">
                            <Spinner style={{ marginRight: 12 }} />
                            Calculating action, please hold on.
                        </div>
                    </div>
                ))}
        </>
    )
}
