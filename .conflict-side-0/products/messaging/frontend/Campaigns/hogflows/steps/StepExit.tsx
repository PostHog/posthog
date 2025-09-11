import { Node } from '@xyflow/react'

import { HogFlowAction } from '../types'

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function StepExitConfiguration(_: { node: Node<Extract<HogFlowAction, { type: 'exit' }>> }): JSX.Element {
    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Exit</p>
            </div>
        </>
    )
}
