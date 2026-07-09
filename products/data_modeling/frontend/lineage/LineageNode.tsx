import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import React, { useCallback, useState } from 'react'

import { IconActivity, IconClockRewind, IconPencil, IconPlay, IconPlayFilled, IconTarget } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { ElkDirection, NodeHandle } from 'scenes/data-warehouse/scene/modeling/types'

import { DataModelingJobStatus, DataModelingNode } from '~/types'

import { syncIntervalToShorthand } from 'products/data_warehouse/frontend/utils'

import { NODE_TYPE_TAG_SETTINGS } from './nodeStyles'

export type LineageVariant = 'full' | 'canvas'

/** Fields the node renders — a superset caller (DataModelingNode) satisfies this structurally. */
export type LineageNodeShape = Pick<
    DataModelingNode,
    | 'id'
    | 'name'
    | 'type'
    | 'sync_interval'
    | 'last_run_at'
    | 'last_run_status'
    | 'upstream_count'
    | 'downstream_count'
    | 'user_tag'
>

export interface LineageNodeState {
    isCurrent?: boolean
    isRunning?: boolean
    /** Dimmed when a search is active and this node is not a match */
    isDimmed?: boolean
    /** Ringed when a search or type filter highlights this node */
    isHighlighted?: boolean
}

export interface LineageNodeCallbacks {
    onClick?: () => void
    onEdit?: () => void
    onMaterialize?: () => void
    onRunUpstream?: () => void
    onRunDownstream?: () => void
    onMouseEnter?: () => void
    onMouseLeave?: () => void
}

export interface LineageNodeData extends Record<string, unknown> {
    node: LineageNodeShape
    variant: LineageVariant
    direction: ElkDirection
    state: LineageNodeState
    callbacks: LineageNodeCallbacks
    handles: NodeHandle[]
}

function NodeTypeTag({ type }: { type: DataModelingNode['type'] }): JSX.Element {
    const { label, color } = NODE_TYPE_TAG_SETTINGS[type]
    return (
        <span
            className="text-[10px] lowercase tracking-wide px-1 rounded border-1"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color,
                backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)`,
                borderColor: `color-mix(in srgb, ${color} 80%, transparent)`,
            }}
        >
            {label}
        </span>
    )
}

function StatusDot({ status }: { status?: DataModelingJobStatus }): JSX.Element {
    return (
        <Tooltip title={status ?? 'Not run yet'}>
            <div
                className={clsx(
                    'rounded-full w-3 h-3 border-1 border-primary',
                    status === 'Completed' && 'bg-success',
                    status === 'Running' && 'bg-warning',
                    status === 'Failed' && 'bg-danger',
                    status === 'Cancelled' && 'bg-warning',
                    !status && 'bg-surface-primary'
                )}
            />
        </Tooltip>
    )
}

function RunArrow({
    direction,
    layoutDirection,
    onClick,
}: {
    direction: 'upstream' | 'downstream'
    layoutDirection: ElkDirection
    onClick: (e: React.MouseEvent) => void
}): JSX.Element {
    const upstream = direction === 'upstream'
    return (
        <Tooltip title={`Run all ${direction} nodes including this one`}>
            <button
                type="button"
                onClick={onClick}
                className={clsx(
                    'absolute flex items-center justify-center cursor-pointer z-10 w-5 h-5 rounded-full bg-[var(--primary-3000)]',
                    layoutDirection === 'DOWN'
                        ? upstream
                            ? 'left-1/2 -translate-x-1/2 -top-3'
                            : 'left-1/2 -translate-x-1/2 -bottom-3'
                        : upstream
                          ? 'top-1/2 -translate-y-1/2 -left-3'
                          : 'top-1/2 -translate-y-1/2 -right-3'
                )}
            >
                <IconPlayFilled
                    className={clsx(
                        'w-2 h-2 text-white/80',
                        layoutDirection === 'DOWN'
                            ? upstream
                                ? '-rotate-90'
                                : 'rotate-90'
                            : upstream
                              ? 'rotate-180'
                              : ''
                    )}
                />
            </button>
        </Tooltip>
    )
}

function MetadataBar({ node }: { node: LineageNodeShape }): JSX.Element {
    return (
        <div className="flex items-center bg-primary dark:bg-primary/60 rounded-b-lg px-2.5 py-1.5 justify-between">
            <div className="flex gap-1 text-[10px] items-center">
                <IconClockRewind className="scale-x-[-1]" />
                <Tooltip title={node.sync_interval ? null : 'This node is not set to sync on a schedule yet'}>
                    {syncIntervalToShorthand(node.sync_interval)}
                </Tooltip>
                <IconActivity />
                {node.last_run_at ? (
                    <TZLabel
                        className="text-[10px]"
                        time={node.last_run_at}
                        formatDate="MMM D"
                        formatTime="HH:mm"
                        showPopover={false}
                    />
                ) : (
                    <Tooltip title="This node has not been run yet">Never</Tooltip>
                )}
            </div>
            <StatusDot status={node.last_run_status} />
        </div>
    )
}

export function LineageNode({ data }: { data: LineageNodeData }): JSX.Element {
    const { node, variant, direction, state, callbacks } = data
    const [isHovered, setIsHovered] = useState(false)

    const showMetadata = node.type === 'matview' || node.type === 'endpoint'
    const showRunArrows = variant === 'canvas' && isHovered && !state.isRunning
    const { color } = NODE_TYPE_TAG_SETTINGS[node.type]

    const handleMouseEnter = useCallback(() => {
        setIsHovered(true)
        callbacks.onMouseEnter?.()
    }, [callbacks])
    const handleMouseLeave = useCallback(() => {
        setIsHovered(false)
        callbacks.onMouseLeave?.()
    }, [callbacks])

    const stop = (fn?: () => void) => (e: React.MouseEvent) => {
        e.stopPropagation()
        fn?.()
    }

    return (
        <div
            className={clsx(
                'relative rounded-lg border bg-bg-light cursor-pointer min-w-[180px]',
                state.isRunning && 'border-warning ring-2 ring-warning/30 animate-pulse',
                !state.isRunning && state.isHighlighted && 'border-link ring-2 ring-link/30',
                !state.isRunning && !state.isHighlighted && !state.isCurrent && 'border-border',
                state.isCurrent && 'border-2'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                opacity: state.isDimmed ? 0.5 : 1,
                borderColor: state.isCurrent ? color : undefined,
            }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            onClick={callbacks.onClick}
        >
            {data.handles.map((handle) => (
                <Handle
                    key={handle.id}
                    id={handle.id}
                    type={handle.type}
                    position={handle.position ?? (handle.type === 'target' ? Position.Left : Position.Right)}
                    className="opacity-0"
                    isConnectable={false}
                />
            ))}

            {showRunArrows && node.upstream_count > 0 && callbacks.onRunUpstream && (
                <RunArrow direction="upstream" layoutDirection={direction} onClick={stop(callbacks.onRunUpstream)} />
            )}
            {showRunArrows && node.downstream_count > 0 && callbacks.onRunDownstream && (
                <RunArrow
                    direction="downstream"
                    layoutDirection={direction}
                    onClick={stop(callbacks.onRunDownstream)}
                />
            )}

            <div className="px-3 pt-3">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1 min-w-0">
                        {state.isCurrent && (
                            <Tooltip title="This is the currently viewed node">
                                <IconTarget className="text-warning text-sm shrink-0" />
                            </Tooltip>
                        )}
                        <NodeTypeTag type={node.type} />
                    </div>
                    {node.user_tag && (
                        <span className="text-[10px] text-muted lowercase tracking-wide px-1 rounded bg-primary dark:bg-primary/20 border-1 border-black/20">
                            #{node.user_tag}
                        </span>
                    )}
                </div>
                <div className="flex items-center justify-between gap-2 py-2">
                    <span className="font-medium text-sm truncate">{node.name}</span>
                    {callbacks.onEdit && (
                        <LemonButton
                            size="xxsmall"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={stop(callbacks.onEdit)}
                        />
                    )}
                    {callbacks.onMaterialize && (node.type === 'matview' || node.type === 'endpoint') && (
                        <Tooltip title={state.isRunning ? null : 'Run this node'}>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={stop(callbacks.onMaterialize)}
                                disabledReason={state.isRunning && 'This node is already running...'}
                                icon={state.isRunning ? <Spinner textColored /> : <IconPlay className="w-3 h-3" />}
                            />
                        </Tooltip>
                    )}
                </div>
            </div>
            {showMetadata && <MetadataBar node={node} />}
        </div>
    )
}

export const LINEAGE_NODE_TYPES = { lineage: LineageNode }
