import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import React, { useCallback, useState } from 'react'

import {
    IconActivity,
    IconClockRewind,
    IconCopy,
    IconExternal,
    IconPauseFilled,
    IconPencil,
    IconPlay,
    IconPlayFilled,
    IconTarget,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DataModelingNode } from '~/types'

import { MATERIALIZING_TYPES } from 'products/data_modeling/frontend/freshness'
import { servingSuspension } from 'products/data_modeling/frontend/suspension'
import { syncIntervalToShorthand } from 'products/data_warehouse/frontend/utils'

import { ElkDirection, NodeHandle } from './autolayout'
import { NODE_TYPE_TAG_SETTINGS, statusBackgroundClass } from './nodeStyles'
import { NodeTypeTag } from './NodeTypeTag'

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
    | 'suspended'
    | 'lineage_issue'
>

export interface LineageNodeState {
    isCurrent?: boolean
    isRunning?: boolean
    /** Ringed when a search or type filter highlights this node */
    isHighlighted?: boolean
    isSelected?: boolean
    /** Faded while another node's lineage is selected */
    isDimmed?: boolean
    loading?: 'placeholder' | 'focus'
}

export interface LineageNodeCallbacks {
    onClick?: (event: React.MouseEvent | React.KeyboardEvent) => void
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
    draggable?: boolean
    openUrl?: string
    selectable?: boolean
    state: LineageNodeState
    callbacks: LineageNodeCallbacks
    handles: NodeHandle[]
}

export function lineageIssueMessage(issue: NonNullable<DataModelingNode['lineage_issue']>): string {
    if (issue.kind === 'sync_failed') {
        return `Lineage could not be refreshed: ${issue.detail}`
    }
    return `Couldn't find ${issue.detail}. This may read a table that was renamed or removed.`
}

/** The warning mark drawn on a lineage node, and repeated beside the name in the editor's table. */
export function LineageIssueMarker({ issue }: { issue: NonNullable<DataModelingNode['lineage_issue']> }): JSX.Element {
    const message = lineageIssueMessage(issue)
    return (
        <Tooltip title={message}>
            <span className="flex items-center" role="img" aria-label={message}>
                <IconWarning className="text-warning text-sm" />
            </span>
        </Tooltip>
    )
}

function StatusDot({ node }: { node: LineageNodeShape }): JSX.Element {
    const suspension = servingSuspension(node.suspended)
    if (suspension) {
        return (
            <Tooltip
                title={
                    <div className="flex flex-col gap-1">
                        <div>Suspended after repeated failures</div>
                        <div className="opacity-75">{suspension.reason}</div>
                    </div>
                }
                interactive
            >
                <IconPauseFilled className="text-warning text-sm" />
            </Tooltip>
        )
    }
    return (
        <Tooltip title={node.last_run_status ?? 'Not run yet'}>
            <div
                className={clsx(
                    'rounded-full w-3 h-3 border-1 border-primary',
                    node.last_run_status ? statusBackgroundClass(node.last_run_status) : 'bg-surface-primary'
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
                    <Tooltip title="Last successful run.">
                        <TZLabel
                            className="text-[10px]"
                            time={node.last_run_at}
                            formatDate="MMM D"
                            formatTime="HH:mm"
                            showPopover={false}
                        />
                    </Tooltip>
                ) : (
                    <Tooltip title="This model has never finished a run">Never succeeded</Tooltip>
                )}
            </div>
            <StatusDot node={node} />
        </div>
    )
}

function LineageNodeContextMenu({
    data,
    children,
}: {
    data: LineageNodeData
    children: React.ReactElement
}): JSX.Element {
    const { node, openUrl } = data
    const trigger = (
        <Tooltip title={node.name} delayMs={500}>
            {openUrl ? <ContextMenuTrigger asChild>{children}</ContextMenuTrigger> : children}
        </Tooltip>
    )

    if (!openUrl) {
        return trigger
    }

    return (
        <ContextMenu>
            {trigger}
            <ContextMenuContent>
                <ContextMenuGroup>
                    <ContextMenuItem
                        asChild
                        onClick={() => window.open(openUrl, '_blank', 'noopener')}
                        data-attr="lineage-node-menu-open"
                    >
                        <ButtonPrimitive menuItem>
                            <IconExternal />
                            Open in new tab
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    <ContextMenuItem
                        asChild
                        onClick={() => void copyToClipboard(node.name, 'node name')}
                        data-attr="lineage-node-menu-copy-name"
                    >
                        <ButtonPrimitive menuItem>
                            <IconCopy />
                            Copy name
                        </ButtonPrimitive>
                    </ContextMenuItem>
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

export function LineageNode({ data }: { data: LineageNodeData }): JSX.Element {
    const { node, variant, direction, state, callbacks } = data
    const [isHovered, setIsHovered] = useState(false)
    const loadingRef = useCancelAnimationsOnUnmount<HTMLDivElement>()

    const showMetadata = MATERIALIZING_TYPES.has(node.type)
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

    if (state.loading) {
        return (
            <div
                ref={loadingRef}
                className={clsx(
                    'relative flex h-full w-full min-w-[180px] animate-pulse flex-col rounded-lg border bg-bg-light/70 motion-reduce:animate-none',
                    state.loading === 'focus' ? 'border-border' : 'border-border/50'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    borderColor:
                        state.loading === 'focus' ? `color-mix(in srgb, ${color} 60%, transparent)` : undefined,
                }}
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
                <div className="flex flex-1 flex-col justify-center gap-2 px-3">
                    {state.loading === 'focus' ? (
                        <div className="opacity-70">
                            <NodeTypeTag type={node.type} />
                        </div>
                    ) : (
                        <LemonSkeleton className="h-4 w-16" active={false} />
                    )}
                    {node.name ? (
                        <span
                            className={clsx(
                                'truncate text-sm font-medium',
                                state.loading === 'focus' ? 'text-primary' : 'text-secondary'
                            )}
                        >
                            {node.name}
                        </span>
                    ) : (
                        <LemonSkeleton className="h-4 w-4/5" active={false} />
                    )}
                </div>
                <div className="flex h-6 items-center rounded-b-lg bg-primary/50 px-3">
                    <LemonSkeleton className="h-2 w-2/3" />
                </div>
            </div>
        )
    }

    const stop = (fn?: () => void) => (e: React.MouseEvent) => {
        e.stopPropagation()
        fn?.()
    }

    const destination = node.type === 'metric' ? 'the metric' : node.type === 'insight' ? 'the insight' : 'the model'
    const cardAction = data.selectable ? 'highlights its lineage' : `opens ${destination}`
    const ariaLabel = [
        `${node.name}, ${NODE_TYPE_TAG_SETTINGS[node.type].label.toLowerCase()}, ${cardAction}`,
        node.lineage_issue && lineageIssueMessage(node.lineage_issue),
    ]
        .filter(Boolean)
        .join('. ')

    const nodeCard = (
        <div
            className={clsx(
                'group/lineage-node relative pointer-events-auto rounded-lg border bg-bg-light min-w-[180px]',
                data.draggable && 'cursor-grab active:cursor-grabbing',
                !data.draggable && callbacks.onClick && 'cursor-pointer',
                state.isRunning && 'animate-pulse',
                state.isRunning && !state.isSelected && 'border-warning ring-2 ring-warning/30',
                state.isSelected && 'border-link ring-4 ring-link/40',
                !state.isRunning && !state.isSelected && state.isHighlighted && 'border-link ring-2 ring-link/30',
                !state.isRunning && !state.isSelected && !state.isHighlighted && !state.isCurrent && 'border-border',
                node.lineage_issue && !state.isRunning && !state.isSelected && !state.isHighlighted && 'border-warning',
                state.isCurrent && 'border-2',
                state.isDimmed && 'opacity-30'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: state.isCurrent ? color : undefined,
            }}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            onClick={callbacks.onClick}
            data-attr="lineage-node"
        >
            {callbacks.onClick && (
                <button
                    type="button"
                    className="absolute inset-0 pointer-events-none rounded-lg focus-visible:ring-4 focus-visible:ring-link/40"
                    onClick={(event) => {
                        event.stopPropagation()
                        callbacks.onClick?.(event)
                    }}
                    aria-label={ariaLabel}
                />
            )}
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
                        {node.lineage_issue && <LineageIssueMarker issue={node.lineage_issue} />}
                    </div>
                    <div className="flex items-center gap-1">
                        {node.user_tag && (
                            <span className="text-[10px] text-muted lowercase tracking-wide px-1 rounded bg-primary dark:bg-primary/20 border-1 border-black/20">
                                #{node.user_tag}
                            </span>
                        )}
                        {data.openUrl && (
                            <LemonButton
                                className="nodrag nopan relative z-10 opacity-0 transition-opacity group-hover/lineage-node:opacity-100 group-focus-within/lineage-node:opacity-100"
                                size="xxsmall"
                                type="secondary"
                                to={data.openUrl}
                                targetBlank
                                stopPropagation
                                tooltip="Open in new tab"
                                aria-label={`Open ${node.name} in new tab`}
                                icon={<IconExternal />}
                                data-attr="lineage-node-open"
                            />
                        )}
                    </div>
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
                    {callbacks.onMaterialize && MATERIALIZING_TYPES.has(node.type) && (
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

    return <LineageNodeContextMenu data={data}>{nodeCard}</LineageNodeContextMenu>
}

export const LINEAGE_NODE_TYPES = { lineage: LineageNode }
