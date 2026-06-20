import clsx from 'clsx'
import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { SandboxToolRow } from './SandboxToolRow'
import { compactInput, formatInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolContentPre, ToolTitle } from './toolRowPrimitives'
import { resolveToolRowChrome } from './toolRowShared'

/**
 * The catch-all tool card — user-installed MCP tools, unmapped PostHog `exec` inner tools, and Claude
 * built-ins without a bespoke renderer. MCP tools show a `server - tool (MCP)` header with a compact
 * input preview; non-MCP built-ins show their friendly title. The body (only once completed) shows the
 * pretty-printed input and any text output. Replaces the old `FallbackMcpToolRenderer` card.
 */
export const GenericMcpToolRenderer = memo(function GenericMcpToolRenderer(
    props: SandboxToolRendererProps
): JSX.Element {
    const { message, icon, displayName } = props
    const chrome = resolveToolRowChrome(props)

    const isPostHogExec = !!message.innerToolName
    const isMcp =
        isPostHogExec || (!!message.rawServerName && !!message.rawToolName && message.rawServerName !== 'claude')

    const serverName = isPostHogExec ? 'posthog' : message.rawServerName
    const toolLabel =
        message.innerToolName || message.rawToolName || message.claudeToolName || displayName || message.resolvedKey
    const inputForPreview = message.innerInput ?? message.rawInput
    const hasInput = !!inputForPreview && Object.keys(inputForPreview).length > 0
    const preview = hasInput ? compactInput(inputForPreview) : ''

    const header = isMcp ? (
        <>
            <span className="text-[13px] text-muted">{serverName} -</span>
            <span className="text-[13px] text-secondary font-medium">{toolLabel}</span>
            <span className="text-[13px] text-muted">(MCP)</span>
            {preview && <span className="text-[13px] text-link font-mono truncate max-w-full">{preview}</span>}
        </>
    ) : (
        <>
            <ToolTitle>{message.title || displayName || toolLabel}</ToolTitle>
            {preview && <span className="text-[13px] text-link font-mono truncate max-w-full">{preview}</span>}
        </>
    )

    const output = stripCodeFences(getContentText(message.content))
    const showBody = message.status === 'completed' && (!!output || hasInput)
    const content = showBody ? (
        <div className="flex flex-col gap-2 min-w-0">
            {hasInput && <ToolContentPre>{formatInput(inputForPreview)}</ToolContentPre>}
            {output && (
                <div className={clsx('min-w-0', hasInput && 'border-t border-border-secondary pt-2')}>
                    <ToolContentPre>{output}</ToolContentPre>
                </div>
            )}
        </div>
    ) : undefined

    return (
        <SandboxToolRow
            icon={icon ?? <IconWrench />}
            isLoading={chrome.isLoading}
            isFailed={chrome.isFailed}
            wasCancelled={chrome.wasCancelled}
            errorMessage={chrome.errorMessage}
            content={content}
            debugDetails={chrome.debugDetails}
        >
            {header}
        </SandboxToolRow>
    )
})
