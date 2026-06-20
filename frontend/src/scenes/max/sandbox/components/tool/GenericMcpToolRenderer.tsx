import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { SandboxToolActivity } from './SandboxToolActivity'
import { compactInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolOutput } from './ToolOutput'

/**
 * The catch-all tool card — user-installed MCP tools, unmapped PostHog `exec` inner tools, and Claude
 * built-ins without a bespoke renderer. MCP tools show a `server - tool (MCP)` title with a compact
 * input preview on the second line; non-MCP built-ins show their friendly title. The body shows any
 * text output. Replaces the old `FallbackMcpToolRenderer`.
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

    const title = isMcp ? (
        <>
            <span className="text-muted">{serverName} -</span> <span className="font-medium">{toolLabel}</span>{' '}
            <span className="text-muted">(MCP)</span>
        </>
    ) : (
        message.title || displayName || toolLabel
    )

    return (
        <SandboxToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={title}
            subtitle={preview ? <span className="font-mono text-link">{preview}</span> : undefined}
            body={output ? <ToolOutput>{output}</ToolOutput> : undefined}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})
