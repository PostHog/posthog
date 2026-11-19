import { Handle, NodeProps, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { DEPENDENCY_KIND_LABEL, FAILING_ERROR_RATE } from './dependencies'
import type { DependencyMapNode } from './dependencies'
import { dependenciesLogic } from './dependenciesLogic'
import { formatPercent } from './healthDisplay'

export function DependencyNode({ data }: NodeProps<DependencyMapNode>): JSX.Element {
    const { dependencyService } = useValues(dependenciesLogic)
    const { setDependencyService } = useActions(dependenciesLogic)
    const failing = data.requests > 0 && data.errorRate >= FAILING_ERROR_RATE

    return (
        <>
            <Handle type="target" position={Position.Left} isConnectable={false} className="opacity-0" />
            <button
                type="button"
                onClick={() => setDependencyService(dependencyService === data.name ? null : data.name)}
                aria-pressed={dependencyService === data.name}
                className={clsx(
                    'flex h-16 w-[200px] cursor-pointer flex-col justify-center gap-0.5 rounded border bg-surface-primary px-3 text-left',
                    data.inferred && 'border-dashed',
                    failing ? 'border-danger' : 'border-primary',
                    dependencyService === data.name && 'ring-2 ring-accent'
                )}
                data-attr="apm-dependency-node"
            >
                <span className="truncate font-semibold">{data.name}</span>
                <span className="font-mono text-xs text-secondary">
                    {data.inferred ? `${DEPENDENCY_KIND_LABEL[data.kind]}, inferred` : DEPENDENCY_KIND_LABEL[data.kind]}
                    {data.requests > 0 ? ` · ${formatPercent(data.errorRate)} errors` : ''}
                </span>
            </button>
            <Handle type="source" position={Position.Right} isConnectable={false} className="opacity-0" />
        </>
    )
}
