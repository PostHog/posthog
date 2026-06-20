import clsx from 'clsx'
import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { SandboxToolActivity } from './SandboxToolActivity'
import { compactInput, formatInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolOutput } from './ToolOutput'

/**
 * The catch-all tool card — user-installed MCP tools, unmapped PostHog `exec` inner tools, and Claude
 * built-ins without a bespoke renderer. PostHog `exec` inner tools read `Call <tool>`; other MCP tools
 * read `Call <server> – <tool> (MCP)`; non-MCP built-ins show their friendly title. A compact input
 * preview sits on the second line and the body shows any text output. Replaces the old
 * `FallbackMcpToolRenderer`.
 */
export const GenericMcpToolRenderer = memo(function GenericMcpToolRenderer(
    props: SandboxToolRendererProps
): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props

    const isPostHogExec = !!message.innerToolName
    const isMcp =
        isPostHogExec || (!!message.rawServerName && !!message.rawToolName && message.rawServerName !== 'claude')
    const serverName = isPostHogExec ? 'posthog' : message.rawServerName
    const toolLabel =
        message.innerToolName || message.rawToolName || message.claudeToolName || displayName || message.resolvedKey
    const inputForPreview = message.innerInput ?? message.rawInput
    const hasInput = !!inputForPreview && Object.keys(inputForPreview).length > 0
    const preview = hasInput ? compactInput(inputForPreview) : ''
    const output = stripCodeFences(getContentText(message.content))

    // A single wrapping span keeps the title as one flex item — the header's `inline-flex` wrapper drops
    // whitespace between sibling flex items, so spaces are baked into the spans here, not between them.
    const title = isPostHogExec ? (
        <span>
            <span className="text-muted">Call </span>
            <span className="font-medium">{toolLabel}</span>
        </span>
    ) : isMcp ? (
        <span>
            <span className="text-muted">Call {serverName} – </span>
            <span className="font-medium">{toolLabel}</span>
            <span className="text-muted"> (MCP)</span>
        </span>
    ) : (
        message.title || displayName || toolLabel
    )

    // Subagent / MCP / unmapped tools show both the full input and the text output in the body.
    const formattedInput = hasInput ? formatInput(inputForPreview) : ''
    const body =
        formattedInput || output ? (
            <div className="flex flex-col gap-2 min-w-0">
                {formattedInput && <ToolOutput>{formattedInput}</ToolOutput>}
                {output && (
                    <div className={clsx('min-w-0', formattedInput && 'border-t border-border-secondary pt-2')}>
                        <ToolOutput>{output}</ToolOutput>
                    </div>
                )}
            </div>
        ) : undefined

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={title}
            subtitle={preview ? <span className="font-mono text-link">{preview}</span> : undefined}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})
