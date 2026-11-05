import { Handle, NodeProps, Position } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { formatPercent, formatRate } from './healthDisplay'
import type { ServiceMapNode as ServiceMapNodeType } from './serviceMap'

export function ServiceMapNode({ data }: NodeProps<ServiceMapNodeType>): JSX.Element {
    const { selectedMapServiceName, servicesHealthLoading } = useValues(applicationObservabilityLogic)
    const { setSelectedMapService } = useActions(applicationObservabilityLogic)
    const status = data.service?.status
    const failing = status === 'serious' || status === 'critical'

    return (
        <>
            <Handle type="target" position={Position.Left} isConnectable={false} className="opacity-0" />
            <button
                type="button"
                onClick={() => setSelectedMapService(data.name)}
                aria-pressed={selectedMapServiceName === data.name}
                className={clsx(
                    'flex h-16 w-[200px] cursor-pointer flex-col justify-center gap-0.5 rounded border bg-surface-primary px-3 text-left',
                    !data.service && 'border-dashed',
                    failing ? 'border-danger' : status === 'warning' ? 'border-warning' : 'border-primary',
                    selectedMapServiceName === data.name && 'ring-2 ring-accent'
                )}
                data-attr="apm-map-node"
            >
                <span className="truncate font-semibold">{data.name}</span>
                <span className="font-mono text-xs text-secondary">
                    {data.service
                        ? `${formatRate(data.service.health.request_rate)} · ${formatPercent(data.service.health.error_rate)} errors`
                        : servicesHealthLoading
                          ? 'Loading health'
                          : 'No health data in this environment'}
                </span>
            </button>
            <Handle type="source" position={Position.Right} isConnectable={false} className="opacity-0" />
        </>
    )
}
