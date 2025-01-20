import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { humanFriendlyDetailedTime } from 'lib/utils'
import GenericNode from 'scenes/data-model/Node'
import { NodeCanvas } from 'scenes/data-model/NodeCanvas'
import { Node } from 'scenes/data-model/types'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { StatusTagSetting } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'

import { lineageTabLogic } from './lineageTabLogic'

export function LineageTab(): JSX.Element {
    const { allNodes } = useValues(lineageTabLogic)
    const { dataWarehouseSavedQueryMapById } = useValues(dataWarehouseViewsLogic)
    const { runDataWarehouseSavedQuery } = useActions(dataWarehouseViewsLogic)

    const renderNode = (node: Node, ref: (el: HTMLDivElement | null) => void): JSX.Element => (
        <GenericNode pref={ref}>
            <div className="flex flex-col max-w-full">
                <div className="flex flex-wrap justify-between gap-2">
                    <div className="font-bold break-all">{node.name}</div>
                    {node.savedQueryId && (
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            onClick={() => node.savedQueryId && runDataWarehouseSavedQuery(node.savedQueryId)}
                        >
                            Run
                        </LemonButton>
                    )}
                </div>
                {node.savedQueryId && dataWarehouseSavedQueryMapById[node.savedQueryId]?.status && (
                    <div className="text-xs mt-2 max-w-full">
                        <LemonTag
                            type={
                                (dataWarehouseSavedQueryMapById[node.savedQueryId]?.status &&
                                    StatusTagSetting[
                                        dataWarehouseSavedQueryMapById[node.savedQueryId].status as string
                                    ]) ||
                                'default'
                            }
                            className="break-words"
                        >
                            {dataWarehouseSavedQueryMapById[node.savedQueryId]?.status}
                        </LemonTag>
                    </div>
                )}
                {node.savedQueryId && dataWarehouseSavedQueryMapById[node.savedQueryId]?.last_run_at && (
                    <span className="text-xs mt-2 max-w-full break-words">
                        {`Last calculated ${humanFriendlyDetailedTime(
                            dataWarehouseSavedQueryMapById[node.savedQueryId]?.last_run_at
                        )}`}
                    </span>
                )}
            </div>
        </GenericNode>
    )

    return (
        <div className="flex flex-1 relative bg-dark z-0">
            <div className="absolute inset-0 overflow-hidden">
                <NodeCanvas nodes={allNodes} renderNode={renderNode} />
            </div>
        </div>
    )
}
