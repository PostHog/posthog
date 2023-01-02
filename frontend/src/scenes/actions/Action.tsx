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
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'

export const scene: SceneExport = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: parseInt(id) }),
}

export function Action({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const fixedFilters = { action_id: id }

    const { push } = useActions(router)

    const { action, isComplete } = useValues(actionLogic)
    const { loadAction } = useActions(actionLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]

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
                            This is the list of <strong>recent</strong> events that match this action.
                            {action?.last_calculated_at ? (
                                <>
                                    {' '}
                                    Last calculated: <b>{dayjs(action.last_calculated_at).fromNow()}</b>.
                                </>
                            ) : (
                                ''
                            )}
                        </p>
                        <div className="pt-4 border-t" />
                        {featureDataExploration ? (
                            <Query
                                query={{
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.EventsQuery,
                                        select: defaultDataTableColumns(NodeKind.EventsQuery),
                                        actionId: id,
                                    },
                                    full: true,
                                    showEventFilter: false,
                                    showPropertyFilter: false,
                                }}
                            />
                        ) : (
                            <EventsTable
                                fixedFilters={fixedFilters}
                                sceneUrl={urls.action(id)}
                                fetchMonths={3}
                                pageKey={`action-${id}-${JSON.stringify(fixedFilters)}`}
                                showEventFilter={false}
                            />
                        )}
                    </div>
                ) : (
                    <div>
                        <h2 className="subtitle">Matching events</h2>
                        <div className="flex items-center">
                            <Spinner className="mr-4" />
                            Calculating action, please hold on.
                        </div>
                    </div>
                ))}
        </>
    )
}
