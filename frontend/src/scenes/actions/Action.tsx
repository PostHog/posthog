import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { actionLogic, ActionLogicProps } from 'scenes/actions/actionLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ActionType } from '~/types'

import { ActionEdit } from './ActionEdit'
import { ActionHogFunctions } from './ActionHogFunctions'

export const scene: SceneExport = {
    logic: actionLogic,
    component: Action,
    paramsToProps: ({ params: { id } }): ActionLogicProps => ({ id: id ? parseInt(id) : undefined }),
}

export function Action({ id }: { id?: ActionType['id'] } = {}): JSX.Element {
    const { action, actionLoading, isComplete } = useValues(actionLogic)

    if (actionLoading) {
        return (
            <div className="space-y-2">
                <LemonSkeleton className="w-1/4 h-6" />

                <LemonSkeleton className="w-1/3 h-10" />
                <LemonSkeleton className="w-1/2 h-6" />

                <div className="flex gap-2">
                    <LemonSkeleton className="w-1/2 h-120" />
                    <LemonSkeleton className="w-1/2 h-120" />
                </div>
            </div>
        )
    }

    if (id && !action) {
        return <NotFound object="action" />
    }

    return (
        <>
            <ActionEdit id={id} action={action} />
            <ActionHogFunctions />
            {id && (
                <>
                    {isComplete ? (
                        <div className="mt-8">
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
                    )}
                </>
            )}
        </>
    )
}
