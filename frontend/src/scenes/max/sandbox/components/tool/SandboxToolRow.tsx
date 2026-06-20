import clsx from 'clsx'
import React, { useState } from 'react'

import { ExpandableIcon, LoadingIcon, StatusIndicators, ToolTitle } from './toolRowPrimitives'

export interface SandboxToolRowProps {
    /** Leading tool icon (12–14px); swapped to a spinner while loading, to ±  on hover when collapsible. */
    icon: React.ReactNode
    isLoading?: boolean
    isFailed?: boolean
    wasCancelled?: boolean
    /** Header nodes. A plain string is wrapped in `ToolTitle`; nodes (chips, mono, stats) pass through. */
    children: React.ReactNode
    /** Collapsible body shown in the indented box when expanded. */
    content?: React.ReactNode
    /** Surfaced as a subtle danger line at the top of the body when the call failed. */
    errorMessage?: string
    /** Expand the body on first render (e.g. while a tool streams live output). */
    defaultOpen?: boolean
    /** Make the header a collapsible trigger even without `content` (e.g. when only debug details exist). */
    collapsible?: boolean
    /** Wrap the body in the bordered box. Defaults to true. */
    boxed?: boolean
    /** Staff/dev-only raw JSON inspector, appended inside the expanded box below the tool body. */
    debugDetails?: React.ReactNode
}

/**
 * The default sandbox tool card — an icon + header line that, when there is a body, becomes a
 * collapse/expand trigger revealing the body in a left-indented bordered box. Replaces the Activity
 * accordion for tool calls: no completion check, no fixed JSON toggles; per-tool renderers compose
 * their own header (`children`) and `content`, and only `(Failed)`/`(Cancelled)` markers surface state.
 */
export function SandboxToolRow({
    icon,
    isLoading = false,
    isFailed = false,
    wasCancelled = false,
    children,
    content,
    errorMessage,
    defaultOpen = false,
    collapsible,
    boxed = true,
    debugDetails,
}: SandboxToolRowProps): JSX.Element {
    const hasErrorLine = isFailed && !!errorMessage
    const hasBody = !!content || !!debugDetails || hasErrorLine
    const expandable = collapsible ?? hasBody
    const [isOpen, setIsOpen] = useState(defaultOpen)

    const header = (
        <div
            className={clsx(
                'group/toolrow flex items-center gap-1.5 min-w-0 select-none',
                expandable && 'cursor-pointer rounded-sm py-0.5 px-1 -mx-1 hover:bg-fill-button-tertiary-hover',
                expandable && isOpen && 'bg-fill-button-tertiary-active'
            )}
            onClick={expandable ? () => setIsOpen((open) => !open) : undefined}
            role={expandable ? 'button' : undefined}
            aria-expanded={expandable ? isOpen : undefined}
        >
            {expandable ? (
                <ExpandableIcon icon={icon} isLoading={isLoading} isExpanded={isOpen} />
            ) : (
                <LoadingIcon icon={icon} isLoading={isLoading} />
            )}
            <div className="flex flex-wrap items-center gap-1 min-w-0">
                {typeof children === 'string' ? <ToolTitle>{children}</ToolTitle> : children}
                <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
            </div>
        </div>
    )

    return (
        <div className="flex flex-col min-w-0 w-full text-[13px]">
            {header}
            {expandable && isOpen && (
                <div
                    className={clsx(
                        'mt-1 mb-3 ml-5 max-w-4xl min-w-0 overflow-hidden',
                        boxed && 'rounded-lg border border-border p-2'
                    )}
                >
                    {hasErrorLine && <div className="text-danger text-[13px] mb-2">{errorMessage}</div>}
                    {content}
                    {debugDetails && <div className={clsx(content && 'mt-2')}>{debugDetails}</div>}
                </div>
            )}
        </div>
    )
}
