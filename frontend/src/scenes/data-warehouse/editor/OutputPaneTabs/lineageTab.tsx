import { useValues } from 'kea'
import GenericNode from 'scenes/data-model/Node'
import { NodeCanvas } from 'scenes/data-model/NodeCanvas'
import { Node } from 'scenes/data-model/types'

import { lineageTabLogic } from './lineageTabLogic'

export function LineageTab(): JSX.Element {
    const { allNodes } = useValues(lineageTabLogic)

    const renderNode = (node: Node, ref: (el: HTMLDivElement | null) => void): JSX.Element => (
        <GenericNode pref={ref}>
            <div className="flex flex-col max-w-full">
                <div className="flex flex-wrap justify-between gap-2">
                    <div className="font-bold break-words">{node.name}</div>
                </div>
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
