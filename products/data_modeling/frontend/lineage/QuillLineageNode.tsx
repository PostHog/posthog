import { Handle, Position } from '@xyflow/react'
import clsx from 'clsx'
import React from 'react'

import { IconActivity, IconClockRewind, IconCopy, IconExternal, IconPauseFilled, IconWarning } from '@posthog/icons'
import {
    Button,
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuTrigger,
    Dot,
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { useCancelAnimationsOnUnmount } from 'lib/hooks/useCancelAnimationsOnUnmount'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { DataModelingNode } from '~/types'

import { MATERIALIZING_TYPES } from 'products/data_modeling/frontend/freshness'
import { servingSuspension } from 'products/data_modeling/frontend/suspension'
import { syncIntervalToShorthand } from 'products/data_warehouse/frontend/utils'

import { LineageNodeData, LineageNodeShape, lineageIssueMessage, lineageNodeAriaLabel } from './LineageNode'
import { QUILL_NODE_TYPE_COLORS, STATUS_DOT_VARIANTS } from './nodeStyles'
import { QuillNodeTypeTag } from './QuillNodeTypeTag'

function HintedText({ hint, children }: { hint: React.ReactNode; children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span />}>{children}</TooltipTrigger>
            <TooltipContent>{hint}</TooltipContent>
        </Tooltip>
    )
}

function QuillLineageIssueMarker({ issue }: { issue: NonNullable<DataModelingNode['lineage_issue']> }): JSX.Element {
    const message = lineageIssueMessage(issue)
    return (
        <HintedText hint={message}>
            <span className="flex items-center" role="img" aria-label={message}>
                <IconWarning className="text-sm text-warning-foreground" />
            </span>
        </HintedText>
    )
}

function QuillStatusDot({ node }: { node: LineageNodeShape }): JSX.Element {
    const suspension = servingSuspension(node.suspended)
    if (suspension) {
        return (
            <HintedText
                hint={
                    <span className="flex flex-col gap-1">
                        <span>Suspended after repeated failures</span>
                        <span className="opacity-75">{suspension.reason}</span>
                    </span>
                }
            >
                <IconPauseFilled className="text-sm text-warning-foreground" />
            </HintedText>
        )
    }
    const status = node.last_run_status
    return (
        <HintedText hint={status ?? 'Not run yet'}>
            <Dot
                variant={(status && STATUS_DOT_VARIANTS[status]) || 'default'}
                pulse={status === 'Running'}
                aria-label={status ?? 'Not run yet'}
            />
        </HintedText>
    )
}

function QuillMetadataBar({ node }: { node: LineageNodeShape }): JSX.Element {
    return (
        <div className="flex items-center justify-between rounded-b-lg bg-muted px-2.5 py-1.5">
            <div className="flex items-center gap-1 text-xxs text-muted-foreground">
                <IconClockRewind className="scale-x-[-1]" />
                {node.sync_interval ? (
                    <span>{syncIntervalToShorthand(node.sync_interval)}</span>
                ) : (
                    <HintedText hint="This node is not set to sync on a schedule yet">
                        {syncIntervalToShorthand(node.sync_interval)}
                    </HintedText>
                )}
                <IconActivity />
                {node.last_run_at ? (
                    <HintedText hint="Last successful run.">
                        <TZLabel
                            className="text-xxs"
                            time={node.last_run_at}
                            formatDate="MMM D"
                            formatTime="HH:mm"
                            showPopover={false}
                        />
                    </HintedText>
                ) : (
                    <HintedText hint="This model has never finished a run">Never succeeded</HintedText>
                )}
            </div>
            <QuillStatusDot node={node} />
        </div>
    )
}

function QuillLineageNodeLoading({ data }: { data: LineageNodeData }): JSX.Element {
    const loadingRef = useCancelAnimationsOnUnmount<HTMLDivElement>()
    const { node, state } = data
    const focused = state.loading === 'focus'
    return (
        <div
            ref={loadingRef}
            className={clsx(
                'relative flex h-full w-full min-w-45 animate-pulse flex-col rounded-lg border bg-card/70 motion-reduce:animate-none',
                focused ? 'border-border' : 'border-border/50'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: focused
                    ? `color-mix(in srgb, ${QUILL_NODE_TYPE_COLORS[node.type]} 60%, transparent)`
                    : undefined,
            }}
        >
            <NodeHandles data={data} />
            <div className="flex flex-1 flex-col justify-center gap-2 px-3">
                {focused ? (
                    <div className="opacity-70">
                        <QuillNodeTypeTag type={node.type} />
                    </div>
                ) : (
                    <Skeleton className="h-4 w-16" />
                )}
                {node.name ? (
                    <span
                        className={clsx(
                            'truncate text-sm font-medium',
                            focused ? 'text-card-foreground' : 'text-muted-foreground'
                        )}
                    >
                        {node.name}
                    </span>
                ) : (
                    <Skeleton className="h-4 w-4/5" />
                )}
            </div>
            <div className="flex h-6 items-center rounded-b-lg bg-muted/50 px-3">
                <Skeleton className="h-2 w-2/3" />
            </div>
        </div>
    )
}

function NodeHandles({ data }: { data: LineageNodeData }): JSX.Element {
    return (
        <>
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
        </>
    )
}

function quillNodeBorderClassName({ node, state }: LineageNodeData): string {
    if (state.isSelected) {
        return 'border-primary ring-4 ring-primary/30'
    }
    if (state.isRunning) {
        return 'border-warning-foreground ring-2 ring-warning'
    }
    if (state.isHighlighted) {
        return 'border-primary ring-2 ring-primary/20'
    }
    return node.lineage_issue ? 'border-warning-foreground' : 'border-border'
}

function quillNodeCardClassName(data: LineageNodeData): string {
    return clsx(
        'group/lineage-node relative pointer-events-auto min-w-45 rounded-lg border bg-card text-card-foreground',
        data.draggable ? 'cursor-grab active:cursor-grabbing' : data.callbacks.onClick && 'cursor-pointer',
        data.state.isRunning && 'animate-pulse motion-reduce:animate-none',
        quillNodeBorderClassName(data),
        data.state.isDimmed && 'opacity-30'
    )
}

export function QuillLineageNode({ data }: { data: LineageNodeData }): JSX.Element {
    const { node, state, callbacks, openUrl } = data

    if (state.loading) {
        return <QuillLineageNodeLoading data={data} />
    }

    const card = (
        <div
            className={quillNodeCardClassName(data)}
            onClick={callbacks.onClick}
            onMouseEnter={callbacks.onMouseEnter}
            onMouseLeave={callbacks.onMouseLeave}
            data-attr="lineage-node"
        >
            {callbacks.onClick && (
                <button
                    type="button"
                    className="pointer-events-none absolute inset-0 rounded-lg focus-visible:ring-4 focus-visible:ring-ring/40"
                    onClick={(event) => {
                        event.stopPropagation()
                        callbacks.onClick?.(event)
                    }}
                    aria-label={lineageNodeAriaLabel(node, data.selectable)}
                />
            )}
            <NodeHandles data={data} />
            <div className="px-3 pt-3">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-1">
                        <QuillNodeTypeTag type={node.type} />
                        {node.lineage_issue && <QuillLineageIssueMarker issue={node.lineage_issue} />}
                    </div>
                    <div className="flex items-center gap-1">
                        {node.user_tag && (
                            <span className="rounded border border-border bg-muted px-1 text-xxs lowercase tracking-wide text-muted-foreground">
                                #{node.user_tag}
                            </span>
                        )}
                        {openUrl && (
                            <Button
                                size="icon-xs"
                                variant="outline"
                                className="nodrag nopan relative z-10 opacity-0 transition-opacity group-focus-within/lineage-node:opacity-100 group-hover/lineage-node:opacity-100"
                                render={<LinkPrimitive to={openUrl} target="_blank" />}
                                onClick={(event) => event.stopPropagation()}
                                tooltip="Open in new tab"
                                aria-label={`Open ${node.name} in new tab`}
                                data-attr="lineage-node-open"
                            >
                                <IconExternal />
                            </Button>
                        )}
                    </div>
                </div>
                <div className="flex items-center justify-between gap-2 py-2">
                    <span className="truncate text-sm font-medium">{node.name}</span>
                </div>
            </div>
            {MATERIALIZING_TYPES.has(node.type) && <QuillMetadataBar node={node} />}
        </div>
    )

    const nameHint = (trigger: React.ReactElement): JSX.Element => (
        <Tooltip>
            <TooltipTrigger delay={500} render={trigger} />
            <TooltipContent>{node.name}</TooltipContent>
        </Tooltip>
    )

    if (!openUrl) {
        return nameHint(card)
    }

    return (
        <ContextMenu>
            {nameHint(<ContextMenuTrigger render={card} />)}
            <ContextMenuContent>
                <ContextMenuGroup>
                    <ContextMenuItem
                        onClick={() => window.open(openUrl, '_blank', 'noopener')}
                        data-attr="lineage-node-menu-open"
                    >
                        <IconExternal />
                        Open in new tab
                    </ContextMenuItem>
                    <ContextMenuItem
                        onClick={() => void copyToClipboard(node.name, 'node name')}
                        data-attr="lineage-node-menu-copy-name"
                    >
                        <IconCopy />
                        Copy name
                    </ContextMenuItem>
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

export const QUILL_LINEAGE_NODE_TYPES = { lineage: QuillLineageNode }
