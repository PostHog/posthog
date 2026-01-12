import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect } from 'react'

import { IconDatabase } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import { dataModelingEditorLogic } from './dataModelingEditorLogic'
import { ModelNodeProps } from './types'

export type ReactFlowNodeType = 'model' | 'dropzone'

const NODE_TYPE_SETTINGS: Record<DataModelingNodeType, { label: string; type: LemonTagType; color: string }> = {
    table: { label: 'Table', type: 'default', color: 'var(--muted)' },
    view: { label: 'View', type: 'primary', color: 'var(--primary-3000)' },
    matview: { label: 'Materialized view', type: 'success', color: 'var(--success)' },
}

function DropzoneNodeComponent(): JSX.Element {
    // just implemented to satisfy the interface
    return <></>
}

function ModelNodeComponent(props: ModelNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()
    const { selectedNodeId } = useValues(dataModelingEditorLogic)

    useEffect(() => {
        updateNodeInternals(props.id)
    }, [props.id, updateNodeInternals])

    const settings = NODE_TYPE_SETTINGS[props.data.type]
    const isSelected = selectedNodeId === props.id

    return (
        <div
            className={clsx(
                'transition-all hover:translate-y-[-2px] rounded-lg border bg-surface-light shadow-sm',
                isSelected ? 'border-primary ring-2 ring-primary/20' : 'border-border'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            {props.data.handles?.map((handle) => (
                <Handle key={handle.id} className="opacity-0" {...handle} isConnectable={false} />
            ))}
            <div className="flex items-center gap-2 p-2 h-full">
                <div
                    className="flex items-center justify-center w-8 h-8 rounded"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: `${settings.color}20`, color: settings.color }}
                >
                    <IconDatabase className="text-lg" />
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                    <span className="font-medium text-sm truncate">{props.data.name}</span>
                    <LemonTag type={settings.type} size="small" className="w-fit">
                        {settings.label}
                    </LemonTag>
                </div>
            </div>
        </div>
    )
}

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<any>> = {
    dropzone: DropzoneNodeComponent,
    model: ModelNodeComponent,
}
