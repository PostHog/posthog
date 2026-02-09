import { Handle } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useCallback, useState } from 'react'

import { IconActivity, IconClockRewind, IconPlay, IconPlayFilled } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { DataModelingJobStatus, DataModelingNodeType, DataWarehouseSyncInterval } from '~/types'

import { dataModelingLogic } from './dataModelingLogic'
import type { ElkDirection, NodeData, NodeHandle } from './types'

const NODE_TYPE_SETTINGS: Record<DataModelingNodeType, { label: string; color: string }> = {
    table: { label: 'table', color: 'var(--muted)' },
    view: { label: 'view', color: 'var(--primary-3000)' },
    matview: { label: 'matview', color: 'var(--success)' },
}

function NodeHandles({ handles }: { handles: NodeHandle[] }): JSX.Element {
    return (
        <>
            {handles.map((handle) => (
                <Handle key={handle.id} className="opacity-0" {...handle} isConnectable={false} />
            ))}
        </>
    )
}

function UpstreamArrow({
    onRunUpstream,
    layoutDirection,
}: {
    onRunUpstream: (e: React.MouseEvent) => void
    layoutDirection: ElkDirection
}): JSX.Element {
    return (
        <Tooltip title="Run all upstream nodes including this one">
            <button
                type="button"
                onClick={onRunUpstream}
                className={clsx(
                    'absolute flex items-center justify-center cursor-pointer z-10 w-5 h-5 rounded-full bg-[var(--primary-3000)]',
                    layoutDirection === 'DOWN' ? 'left-1/2 -translate-x-1/2 -top-3' : 'top-1/2 -translate-y-1/2 -left-3'
                )}
            >
                <IconPlayFilled
                    className={clsx('w-2 h-2 text-white/80', layoutDirection === 'DOWN' ? '-rotate-90' : 'rotate-180')}
                />
            </button>
        </Tooltip>
    )
}

function DownstreamArrow({
    layoutDirection,
    onRunDownstream,
}: {
    onRunDownstream: (e: React.MouseEvent) => void
    layoutDirection: ElkDirection
}): JSX.Element {
    return (
        <Tooltip title="Run all downstream nodes including this one">
            <button
                type="button"
                onClick={onRunDownstream}
                className={clsx(
                    'absolute flex items-center justify-center cursor-pointer z-10 w-5 h-5 rounded-full bg-[var(--primary-3000)]',
                    layoutDirection === 'DOWN'
                        ? 'left-1/2 -translate-x-1/2 -bottom-3'
                        : 'top-1/2 -translate-y-1/2 -right-3'
                )}
            >
                <IconPlayFilled
                    className={clsx('w-2 h-2 text-white/80', layoutDirection === 'DOWN' ? 'rotate-90' : '')}
                />
            </button>
        </Tooltip>
    )
}

interface NodeInnerProps extends NodeData {
    layoutDirection: ElkDirection
    onRunUpstream: (e: React.MouseEvent) => void
    onRunDownstream: (e: React.MouseEvent) => void
    onMaterialize: (e: React.MouseEvent) => void
    onNodeClick: () => void
    onMouseEnter: () => void
    onMouseLeave: () => void
}

function NodeTags({ label, color, userTag }: { label: string; color: string; userTag?: string }): JSX.Element {
    return (
        <div className="flex justify-between items-start">
            <span
                className="text-[10px] lowercase tracking-wide px-1 rounded border-1"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    color: color,
                    backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)`,
                    borderColor: `color-mix(in srgb, ${color} 80%, transparent)`,
                }}
            >
                {label}
            </span>
            {userTag && (
                <span className="text-[10px] text-muted lowercase tracking-wide px-1 rounded bg-primary dark:bg-primary/20 border-1 border-black/20">
                    #{userTag}
                </span>
            )}
        </div>
    )
}

function NodeLabelAndAction({
    label,
    showAction,
    action,
    isActionRunning,
}: {
    label: string
    showAction: boolean
    isActionRunning: boolean
    action: (e: React.MouseEvent) => void
}): JSX.Element {
    return (
        <div className="flex items-center justify-between py-2">
            <Tooltip title={label}>
                <span className="font-medium text-sm truncate">{label}</span>
            </Tooltip>
            {showAction && (
                <Tooltip title={isActionRunning ? null : 'Run this node'}>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={action}
                        disabledReason={isActionRunning && 'This node is already running...'}
                        icon={isActionRunning ? <Spinner textColored /> : <IconPlay className="w-3 h-3" />}
                    />
                </Tooltip>
            )}
        </div>
    )
}

function syncIntervalToShorthand(syncInterval: DataWarehouseSyncInterval | undefined): string {
    switch (syncInterval) {
        case '5min':
            return '5m'
        case '30min':
            return '30m'
        case '1hour':
            return '1h'
        case '6hour':
            return '6h'
        case '12hour':
            return '12h'
        case '24hour':
            return '1d'
        case '7day':
            return '1w'
        case '30day':
            return '30d'
        default:
            return '∞'
    }
}

function NodeMetadata({
    type,
    syncInterval,
    lastRunAt,
    lastJobStatus,
}: {
    type: DataModelingNodeType
    syncInterval?: DataWarehouseSyncInterval
    lastRunAt?: string
    lastJobStatus?: DataModelingJobStatus | null
}): JSX.Element | null {
    const shortHandSyncInterval = syncIntervalToShorthand(syncInterval)
    switch (type) {
        case 'matview':
            return (
                <div className="flex items-center bg-primary dark:bg-primary/60 rounded-b-lg px-2.5 py-1.5 justify-between">
                    <div className="flex gap-1 text-[10px]">
                        <IconClockRewind className="scale-x-[-1]" />
                        {syncInterval ? (
                            shortHandSyncInterval
                        ) : (
                            <Tooltip title="This node is not set to sync on a schedule yet">
                                {shortHandSyncInterval}
                            </Tooltip>
                        )}
                        <IconActivity />
                        {lastRunAt ? (
                            <TZLabel
                                className="text-[10px]"
                                time={lastRunAt}
                                formatDate="MMM DD, YYYY"
                                formatTime="HH:mm"
                                showPopover={false}
                            />
                        ) : (
                            <Tooltip title="This node has not been run yet">Never</Tooltip>
                        )}
                    </div>
                    <Tooltip title={lastJobStatus ?? 'This node has not been run yet'}>
                        <div
                            className={clsx(
                                'rounded-full w-4 h-4',
                                lastJobStatus === 'Completed' && 'bg-success border-border border-1',
                                lastJobStatus === 'Failed' && 'bg-danger border-border border-1',
                                lastJobStatus === 'Cancelled' && 'bg-warning border-border border-1',
                                !lastJobStatus && 'bg-surface-primary border-primary border-1'
                            )}
                        />
                    </Tooltip>
                </div>
            )
        default:
            return null
    }
}

const NodeInner = React.memo(function NodeInner({
    name,
    type,
    savedQueryId,
    handles,
    layoutDirection,
    isRunning,
    isSearchMatch,
    isTypeHighlighted,
    lastJobStatus,
    lastRunAt,
    userTag,
    syncInterval,
    upstreamCount,
    downstreamCount,
    onRunUpstream,
    onRunDownstream,
    onMaterialize,
    onNodeClick,
    onMouseEnter,
    onMouseLeave,
}: NodeInnerProps): JSX.Element {
    const [isHovered, setIsHovered] = useState(false)

    const nodeTypeSettings = NODE_TYPE_SETTINGS[type]

    const canRun = type === 'matview' || type === 'view'
    const canOpenInEditor = type !== 'table' && savedQueryId
    const shouldRenderArrows = canRun && isHovered && !isRunning

    const handleMouseEnter = useCallback(() => {
        setIsHovered(true)
        onMouseEnter()
    }, [onMouseEnter])
    const handleMouseLeave = useCallback(() => {
        setIsHovered(false)
        onMouseLeave()
    }, [onMouseLeave])

    return (
        <div
            className={clsx(
                'relative rounded-lg border dark:border-none bg-bg-light',
                isRunning && 'border-warning ring-2 ring-warning/30 animate-pulse',
                !isRunning && (isSearchMatch || isTypeHighlighted) && 'border-link ring-2 ring-link/30',
                !isRunning && !isSearchMatch && !isTypeHighlighted && 'border-border',
                canOpenInEditor && 'cursor-pointer'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                // dims non matched nodes, search match is undefined when the debounced query value is unset
                opacity: isSearchMatch === undefined || isSearchMatch ? 1 : 0.5,
            }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            onClick={onNodeClick}
        >
            {handles && <NodeHandles handles={handles} />}

            {shouldRenderArrows && upstreamCount > 0 && (
                <UpstreamArrow onRunUpstream={onRunUpstream} layoutDirection={layoutDirection} />
            )}

            {shouldRenderArrows && downstreamCount > 0 && (
                <DownstreamArrow onRunDownstream={onRunDownstream} layoutDirection={layoutDirection} />
            )}

            <div className="flex flex-col justify-around px-3 pt-3">
                <NodeTags color={nodeTypeSettings.color} label={nodeTypeSettings.label} userTag={userTag} />
                <NodeLabelAndAction
                    label={name}
                    showAction={canRun && type === 'matview'}
                    isActionRunning={isRunning ?? false}
                    action={onMaterialize}
                />
            </div>
            <NodeMetadata type={type} syncInterval={syncInterval} lastRunAt={lastRunAt} lastJobStatus={lastJobStatus} />
        </div>
    )
})

const NodeComponent = React.memo(function NodeComponent(props: { id: string; data: NodeData }): JSX.Element | null {
    const { runNode, materializeNode, setHoveredNodeId } = useActions(dataModelingLogic)
    const { layoutDirection, highlightedNodeIds, debouncedSearchTerm, parsedSearch } = useValues(dataModelingLogic)
    const { newTab } = useActions(sceneLogic)

    const { id } = props
    const {
        name,
        type,
        savedQueryId,
        handles,
        upstreamCount,
        downstreamCount,
        isRunning,
        isTypeHighlighted,
        lastJobStatus,
        lastRunAt,
        syncInterval,
        userTag,
    } = props.data

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

    const handleMouseEnter = useCallback(() => setHoveredNodeId(id), [id, setHoveredNodeId])
    const handleMouseLeave = useCallback(() => setHoveredNodeId(null), [setHoveredNodeId])

    return (
        <NodeInner
            id={id}
            name={name}
            type={type}
            savedQueryId={savedQueryId}
            handles={handles}
            layoutDirection={layoutDirection}
            isRunning={isRunning ?? false}
            isSearchMatch={isSearchMatch}
            isTypeHighlighted={isTypeHighlighted ?? false}
            lastJobStatus={lastJobStatus}
            lastRunAt={lastRunAt}
            userTag={userTag}
            syncInterval={syncInterval}
            upstreamCount={upstreamCount}
            downstreamCount={downstreamCount}
            onRunUpstream={handleRunUpstream}
            onRunDownstream={handleRunDownstream}
            onMaterialize={handleMaterialize}
            onNodeClick={handleNodeClick}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
        />
    )
})

export const REACT_FLOW_NODE_TYPES = {
    model: NodeComponent,
}
