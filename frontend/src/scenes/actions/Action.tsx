import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { actionLogic, ActionLogicProps } from 'scenes/actions/actionLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ActionType } from '~/types'

import { ActionEdit } from './ActionEdit'

export const scene: SceneExport = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: parseInt(id) }),
}

export function Action({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const { action, isComplete } = useValues(actionLogic)

    return (
        <>
            {(!id || action) && <ActionEdit id={id} action={action} />}
            {id &&
                (isComplete ? (
                    <div>
                        <h2 className="subtitle">Matching events</h2>
                        <p>
                            This is the list of <strong>recent</strong> events that match this action.
                        </p>
                        <div className="pt-4 border-t" />
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
