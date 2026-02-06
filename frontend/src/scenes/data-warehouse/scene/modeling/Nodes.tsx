import { Handle } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useCallback, useState } from 'react'

import { IconCheck, IconPlay, IconPlayFilled, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNodeType } from '~/types'

import { dataModelingNodesLogic } from '../dataModelingNodesLogic'
import { ElkDirection } from './autolayout'
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

interface ModelNodeInnerProps {
    data: ModelNodeProps['data']
    isSelected: boolean
    isRunning: boolean
    isSearchMatch: boolean | undefined
    isTypeHighlighted: boolean
    lastJobStatus: DataModelingJobStatus | undefined
    layoutDirection: ElkDirection
    onRunUpstream: (e: React.MouseEvent) => void
    onRunDownstream: (e: React.MouseEvent) => void
    onMaterialize: (e: React.MouseEvent) => void
    onNodeClick: () => void
}

const ModelNodeInner = React.memo(function ModelNodeInner({
    data,
    isSelected,
    isRunning,
    isSearchMatch,
    isTypeHighlighted,
    lastJobStatus,
    layoutDirection,
    onRunUpstream,
    onRunDownstream,
    onMaterialize,
    onNodeClick,
}: ModelNodeInnerProps): JSX.Element {
    const [isHovered, setIsHovered] = useState(false)

    const settings = NODE_TYPE_SETTINGS[data.type]
    const { userTag, name, type, savedQueryId } = data

    const canRun = type !== 'table'
    const canOpenInEditor = type !== 'table' && savedQueryId
    const hasUpstream = data.upstreamCount > 0
    const hasDownstream = data.downstreamCount > 0

    const handleMouseEnter = useCallback(() => setIsHovered(true), [])
    const handleMouseLeave = useCallback(() => setIsHovered(false), [])

    return (
        <div
            className={clsx(
                'relative rounded-lg border bg-bg-light',
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
                // dims non matched nodes, search match is undefined when the debounced query value is unset
                opacity: isSearchMatch === undefined || isSearchMatch ? 1 : 0.5,
            }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            onClick={onNodeClick}
        >
            {data.handles?.map((handle) => (
                <Handle key={handle.id} className="opacity-0" {...handle} isConnectable={false} />
            ))}

            {lastJobStatus && !isRunning && (
                <div className="absolute -top-1.5 -right-1.5 z-10">
                    <JobStatusBadge status={lastJobStatus} />
                </div>
            )}

            {canRun && isHovered && !isRunning && (
                <>
                    {hasUpstream && (
                        <Tooltip title="Run all upstream nodes including this one">
                            <button
                                type="button"
                                onClick={onRunUpstream}
                                className={clsx(
                                    'absolute w-5 h-5 flex items-center justify-center rounded-full cursor-pointer z-10 bg-gray-600 dark:bg-gray-400',
                                    layoutDirection === 'DOWN'
                                        ? 'left-1/2 -translate-x-1/2 -top-3'
                                        : 'top-1/2 -translate-y-1/2 -left-3'
                                )}
                            >
                                <IconPlayFilled
                                    className={clsx(
                                        'w-2.5 h-2.5 text-white dark:text-gray-900',
                                        layoutDirection === 'DOWN' ? '-rotate-90' : 'rotate-180'
                                    )}
                                />
                            </button>
                        </Tooltip>
                    )}
                    {hasDownstream && (
                        <Tooltip title="Run all downstream nodes including this one">
                            <button
                                type="button"
                                onClick={onRunDownstream}
                                className={clsx(
                                    'absolute w-5 h-5 flex items-center justify-center rounded-full cursor-pointer z-10 bg-gray-600 dark:bg-gray-400',
                                    layoutDirection === 'DOWN'
                                        ? 'left-1/2 -translate-x-1/2 -bottom-3'
                                        : 'top-1/2 -translate-y-1/2 -right-3'
                                )}
                            >
                                <IconPlayFilled
                                    className={clsx(
                                        'w-2.5 h-2.5 text-white dark:text-gray-900',
                                        layoutDirection === 'DOWN' ? 'rotate-90' : ''
                                    )}
                                />
                            </button>
                        </Tooltip>
                    )}
                </>
            )}

            <div className="flex flex-col justify-between px-2.5 py-2 h-full">
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
                                onClick={onMaterialize}
                                disabled={isRunning}
                                icon={isRunning ? <Spinner textColored /> : <IconPlay className="w-3 h-3" />}
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
        </div>
    )
})

const ModelNodeComponent = React.memo(function ModelNodeComponent(props: ModelNodeProps): JSX.Element | null {
    const { runNode, materializeNode } = useActions(dataModelingEditorLogic)
    const { layoutDirection, highlightedNodeIds } = useValues(dataModelingEditorLogic)
    const { newTab } = useActions(sceneLogic)
    const { debouncedSearchTerm, parsedSearch } = useValues(dataModelingNodesLogic)

    const { id, data } = props
    const { name, type, savedQueryId, isSelected, isRunning, isTypeHighlighted, lastJobStatus } = data
    const isSearchMatch = (() => {
        if (debouncedSearchTerm.length === 0) {
            return undefined
        }
        if (parsedSearch.mode !== 'search') {
            // graph traversal for +name, name+, or +name+ syntax
            const highlighted = highlightedNodeIds(parsedSearch.baseName, parsedSearch.mode)
            return highlighted.has(props.id)
        }
        // default text search
        return name.toLowerCase().includes(parsedSearch.baseName.toLowerCase())
    })()

    const handleRunUpstream = useCallback(
        (e: React.MouseEvent): void => {
            e.stopPropagation()
            runNode(id, 'upstream')
        },
        [id, runNode]
    )

    const handleRunDownstream = useCallback(
        (e: React.MouseEvent): void => {
            e.stopPropagation()
            runNode(id, 'downstream')
        },
        [id, runNode]
    )

    const handleMaterialize = useCallback(
        (e: React.MouseEvent): void => {
            e.stopPropagation()
            materializeNode(id)
        },
        [id, materializeNode]
    )

    const canOpenInEditor = type !== 'table' && savedQueryId
    const handleNodeClick = useCallback((): void => {
        if (canOpenInEditor) {
            newTab(urls.sqlEditor({ view_id: savedQueryId }))
        }
    }, [canOpenInEditor, savedQueryId, newTab])

    return (
        <ModelNodeInner
            data={data}
            isSelected={isSelected ?? false}
            isRunning={isRunning ?? false}
            isSearchMatch={isSearchMatch}
            isTypeHighlighted={isTypeHighlighted ?? false}
            lastJobStatus={lastJobStatus}
            layoutDirection={layoutDirection}
            onRunUpstream={handleRunUpstream}
            onRunDownstream={handleRunDownstream}
            onMaterialize={handleMaterialize}
            onNodeClick={handleNodeClick}
        />
    )
})

export const REACT_FLOW_NODE_TYPES = {
    model: ModelNodeComponent,
}
