import { Handle, NodeProps, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { DEPENDENCY_KIND_LABEL, FAILING_ERROR_RATE } from './dependencies'
import type { DependencyMapNode, DependencyNodeData } from './dependencies'
import { dependenciesLogic } from './dependenciesLogic'
import { formatMs, formatPercent } from './healthDisplay'

function nodeDetail(data: DependencyNodeData): string {
    if (data.group) {
        return data.group.p95MaxMs === null ? 'External' : `p95 up to ${formatMs(data.group.p95MaxMs)}`
    }
    return data.inferred ? `${DEPENDENCY_KIND_LABEL[data.kind]}, inferred` : DEPENDENCY_KIND_LABEL[data.kind]
}

export function DependencyNode({ data }: NodeProps<DependencyMapNode>): JSX.Element {
    const { dependencyService } = useValues(dependenciesLogic)
    const { setDependencyService } = useActions(dependenciesLogic)
    const failing = data.requests > 0 && data.errorRate >= FAILING_ERROR_RATE
    const target = data.group?.caller ?? data.name
    const detail = nodeDetail(data)

    return (
        <>
            <Handle type="target" position={Position.Left} isConnectable={false} className="opacity-0" />
            <button
                type="button"
                onClick={() => setDependencyService(dependencyService === target ? null : target)}
                aria-pressed={dependencyService === data.name}
                className={clsx(
                    'flex h-16 w-[200px] cursor-pointer flex-col justify-center gap-0.5 rounded border bg-surface-primary px-3 text-left',
                    data.inferred && 'border-dashed',
                    failing ? 'border-danger' : 'border-primary',
                    dependencyService === data.name && 'ring-2 ring-accent'
                )}
                title={
                    data.group ? `External hosts called by ${data.group.caller}. Select to see each host.` : undefined
                }
                data-attr="apm-dependency-node"
            >
                <span className="truncate font-semibold">
                    {data.group ? `${data.group.hostCount} external hosts` : data.name}
                </span>
                <span className="font-mono text-xs text-secondary">
                    {detail}
                    {data.requests > 0 ? ` · ${formatPercent(data.errorRate)} errors` : ''}
                </span>
            </button>
            <Handle type="source" position={Position.Right} isConnectable={false} className="opacity-0" />
        </>
    )
}
