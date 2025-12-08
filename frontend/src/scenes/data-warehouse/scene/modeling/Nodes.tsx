import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus } from '@posthog/icons'

import { DataModelingNodeType } from '~/types'

import { dataModelingNodesLogic } from '../dataModelingNodesLogic'
import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import { dataModelingEditorLogic } from './dataModelingEditorLogic'
import { DropzoneNodeProps, ModelNodeProps } from './types'

export type ReactFlowNodeType = 'model' | 'dropzone'

const NODE_TYPE_SETTINGS: Record<DataModelingNodeType, { label: string; color: string }> = {
    table: { label: 'table', color: 'var(--muted)' },
    view: { label: 'view', color: 'var(--primary-3000)' },
    matview: { label: 'matview', color: 'var(--success)' },
}

function DropzoneNode({ id }: DropzoneNodeProps): JSX.Element {
    const [isHighlighted, setIsHighlighted] = useState(false)
    const { setHighlightedDropzoneNodeId } = useActions(dataModelingEditorLogic)

    useEffect(() => {
        setHighlightedDropzoneNodeId(isHighlighted ? id : null)
    }, [id, isHighlighted, setHighlightedDropzoneNodeId])

    return (
        <div
            onDragOver={() => setIsHighlighted(true)}
            onDragLeave={() => setIsHighlighted(false)}
            className={clsx(
                'flex justify-center items-center p-2 rounded border border-dashed transition-all cursor-pointer',
                isHighlighted ? 'border-primary bg-surface-primary' : 'border-transparent'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
        >
            <div className="flex flex-col justify-center items-center w-6 h-6 rounded-full border bg-surface-primary">
                <IconPlus className="text-sm text-primary" />
            </div>
        </div>
    )
}

function ModelNodeComponent(props: ModelNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()
    const { selectedNodeId } = useValues(dataModelingEditorLogic)
    const { searchTerm } = useValues(dataModelingNodesLogic)

    useEffect(() => {
        updateNodeInternals(props.id)
    }, [props.id, updateNodeInternals])

    const settings = NODE_TYPE_SETTINGS[props.data.type]
    const isSelected = selectedNodeId === props.id
    const { userTag, name } = props.data

    const isSearchMatch = searchTerm.length > 0 && name.toLowerCase().includes(searchTerm.toLowerCase())

    return (
        <div
            className={clsx(
                'relative transition-all hover:translate-y-[-2px] rounded-lg border shadow-sm bg-bg-light',
                isSearchMatch
                    ? 'border-warning ring-2 ring-warning/50'
                    : isSelected
                      ? 'border-primary ring-2 ring-primary/50'
                      : 'border-border'
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
            <div className="flex flex-col justify-between p-2 h-full">
                <div className="flex justify-between items-start">
                    <span
                        className="text-[10px] lowercase tracking-wide px-1 rounded"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            color: settings.color,
                            backgroundColor: `color-mix(in srgb, ${settings.color} 15%, transparent)`,
                            border: `1px solid color-mix(in srgb, ${settings.color} 30%, transparent)`,
                        }}
                    >
                        {settings.label}
                    </span>
                    {userTag && (
                        <span className="text-[10px] text-muted lowercase tracking-wide px-1 py-px rounded bg-primary/50">
                            #{userTag}
                        </span>
                    )}
                </div>
                <span className="font-medium text-sm truncate">{name}</span>
            </div>
        </div>
    )
}

export const REACT_FLOW_NODE_TYPES: Record<ReactFlowNodeType, React.ComponentType<any>> = {
    dropzone: DropzoneNode,
    model: ModelNodeComponent,
}
