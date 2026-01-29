import { Handle, useUpdateNodeInternals } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheck, IconPlay, IconPlayFilled, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNodeType } from '~/types'

import { dataModelingNodesLogic } from '../dataModelingNodesLogic'
import { NODE_HEIGHT, NODE_WIDTH } from './constants'
import { dataModelingEditorLogic } from './dataModelingEditorLogic'
import { ModelNodeProps } from './types'

const NODE_TYPE_SETTINGS: Record<DataModelingNodeType, { label: string; color: string }> = {
    table: { label: 'table', color: 'var(--muted)' },
    view: { label: 'view', color: 'var(--primary-3000)' },
    matview: { label: 'matview', color: 'var(--success)' },
}

const JOB_STATUS_CONFIG: Record<
    DataModelingJobStatus,
    { icon: React.ComponentType<{ className?: string }>; bgColor: string; iconColor: string; label: string }
> = {
    Completed: { icon: IconCheck, bgColor: 'bg-success', iconColor: 'text-white', label: 'Last run completed' },
    Failed: { icon: IconX, bgColor: 'bg-danger', iconColor: 'text-white', label: 'Last run failed' },
    Running: { icon: Spinner, bgColor: 'bg-warning', iconColor: 'text-white', label: 'Running' },
    Cancelled: { icon: IconWarning, bgColor: 'bg-muted', iconColor: 'text-white', label: 'Last run cancelled' },
}

function JobStatusBadge({ status }: { status: DataModelingJobStatus }): JSX.Element {
    const config = JOB_STATUS_CONFIG[status]
    const Icon = config.icon
    return (
        <Tooltip title={config.label}>
            <div className={clsx('flex items-center justify-center w-5 h-5 rounded-full shadow-sm', config.bgColor)}>
                <Icon className={clsx('w-3 h-3', config.iconColor)} />
            </div>
        </Tooltip>
    )
}

function ModelNodeComponent(props: ModelNodeProps): JSX.Element | null {
    const updateNodeInternals = useUpdateNodeInternals()
    const { selectedNodeId, highlightedNodeType, runningNodeIds, lastJobStatusByNodeId } =
        useValues(dataModelingEditorLogic)
    const { runNode, materializeNode } = useActions(dataModelingEditorLogic)
    const { newTab } = useActions(sceneLogic)
    const { debouncedSearchTerm } = useValues(dataModelingNodesLogic)
    const [isHovered, setIsHovered] = useState(false)

    useEffect(() => {
        updateNodeInternals(props.id)
    }, [props.id, updateNodeInternals])

    const settings = NODE_TYPE_SETTINGS[props.data.type]
    const isSelected = selectedNodeId === props.id
    const { userTag, name, type, savedQueryId } = props.data
    const isRunning = runningNodeIds.has(props.id)
    const lastJobStatus = lastJobStatusByNodeId[props.id]

    const isSearchMatch =
        debouncedSearchTerm.length > 0 && name.toLowerCase().includes(debouncedSearchTerm.toLowerCase())
    const isTypeHighlighted = highlightedNodeType !== null && highlightedNodeType === type

    const canRun = type !== 'table'
    const canOpenInEditor = type !== 'table' && savedQueryId

    const handleRunUpstream = (e: React.MouseEvent): void => {
        e.stopPropagation()
        runNode(props.id, 'upstream')
    }

    const handleRunDownstream = (e: React.MouseEvent): void => {
        e.stopPropagation()
        runNode(props.id, 'downstream')
    }

    const handleMaterialize = (e: React.MouseEvent): void => {
        e.stopPropagation()
        materializeNode(props.id)
    }

    const handleNodeClick = (): void => {
        if (canOpenInEditor) {
            newTab(urls.sqlEditor({ view_id: savedQueryId }))
        }
    }

    return (
        <div
            className={clsx(
                'relative transition-all hover:translate-y-[-2px] rounded-lg border shadow-sm bg-bg-light',
                isRunning
                    ? 'border-warning ring-2 ring-warning/30 animate-pulse'
                    : isSearchMatch
                      ? 'border-link ring-2 ring-link/30'
                      : isTypeHighlighted
                        ? 'border-link ring-2 ring-link/30'
                        : isSelected
                          ? 'border-primary ring-2 ring-primary/50'
                          : 'border-border',
                canOpenInEditor && 'cursor-pointer'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: NODE_WIDTH,
                height: NODE_HEIGHT,
            }}
            onMouseEnter={() => setIsHovered(true)}
            onMouseLeave={() => setIsHovered(false)}
            onClick={handleNodeClick}
        >
            {props.data.handles?.map((handle) => (
                <Handle key={handle.id} className="opacity-0" {...handle} isConnectable={false} />
            ))}

            {lastJobStatus && !isRunning && (
                <div className="absolute -top-1.5 -right-1.5 z-10">
                    <JobStatusBadge status={lastJobStatus} />
                </div>
            )}

            {canRun && isHovered && !isRunning && (
                <>
                    <Tooltip title="Run all upstream nodes including this one">
                        <button
                            type="button"
                            onClick={handleRunUpstream}
                            className="absolute left-1/2 -translate-x-1/2 -top-3 w-5 h-5 flex items-center justify-center rounded-full shadow-sm hover:scale-110 transition-all cursor-pointer z-10 bg-gray-600 dark:bg-gray-400"
                        >
                            <IconPlayFilled className="w-2.5 h-2.5 text-white dark:text-gray-900 -rotate-90" />
                        </button>
                    </Tooltip>
                    <Tooltip title="Run all downstream nodes including this one">
                        <button
                            type="button"
                            onClick={handleRunDownstream}
                            className="absolute left-1/2 -translate-x-1/2 -bottom-3 w-5 h-5 flex items-center justify-center rounded-full shadow-sm hover:scale-110 transition-all cursor-pointer z-10 bg-gray-600 dark:bg-gray-400"
                        >
                            <IconPlayFilled className="w-2.5 h-2.5 text-white dark:text-gray-900 rotate-90" />
                        </button>
                    </Tooltip>
                </>
            )}

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
                <div className="flex items-center justify-between gap-1">
                    <Tooltip title={name}>
                        <span className="font-medium text-sm truncate">{name}</span>
                    </Tooltip>
                    {canRun && (
                        <Tooltip title={isRunning ? 'Running...' : 'Run this node'}>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={handleMaterialize}
                                disabled={isRunning}
                                icon={isRunning ? <Spinner textColored /> : <IconPlay className="w-3 h-3" />}
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
        </div>
    )
}

export const REACT_FLOW_NODE_TYPES = {
    model: ModelNodeComponent,
}
