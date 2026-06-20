import React from 'react'

import { IconWarning, IconWrench } from '@posthog/icons'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet/CodeSnippet'

import type { SandboxToolCallMessage } from '../../maxTypes'
import { MessageTemplate } from '../../messages/MessageTemplate'
import { Activity, ActivityToggleSection, ActivityStatus } from './ActivityPrimitives'

export function SandboxActivity({
    id,
    content,
    substeps,
    state,
    icon,
    animate = true,
    showCompletionIcon = true,
}: {
    id: string
    content: React.ReactNode
    substeps: string[]
    state: ActivityStatus
    icon?: React.ReactNode
    animate?: boolean
    showCompletionIcon?: boolean
}): JSX.Element {
    return (
        <Activity
            id={id}
            title={content}
            substeps={substeps}
            status={state}
            icon={icon}
            animate={animate}
            showCompletionIcon={showCompletionIcon}
        />
    )
}

/**
 * Extracts displayable text from one ACP tool-call content block. ACP nests the real ContentBlock
 * under a `{ type: 'content', content: { type: 'text', text } }` envelope, so unwrap that first;
 * flat `{ type: 'text', text }` blocks are read directly. Non-text blocks fall back to pretty JSON.
 */
export function contentBlockText(block: unknown): string {
    if (!block || typeof block !== 'object') {
        return JSON.stringify(block, null, 2)
    }
    const inner =
        (block as { type?: unknown }).type === 'content' && 'content' in block
            ? (block as { content: unknown }).content
            : block
    if (inner && typeof inner === 'object' && 'text' in inner) {
        return String((inner as { text: unknown }).text)
    }
    return JSON.stringify(block, null, 2)
}

/** Pretty-prints accumulated ACP `content[]` — text frames inline, everything else as JSON. */
export function renderContentBlocks(content: unknown[]): string {
    return content.map(contentBlockText).join('\n')
}

function SandboxToolMessageBubble({ children }: { children: React.ReactNode }): JSX.Element | null {
    if (!children) {
        return null
    }

    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            {children}
        </MessageTemplate>
    )
}

export function SandboxToolActivity({
    message,
    icon,
    displayName,
    children,
}: {
    message: SandboxToolCallMessage
    icon?: JSX.Element
    displayName?: string
    children?: React.ReactNode
}): JSX.Element {
    const headerLabel = message.title || message.innerToolName || displayName || message.rawToolName || 'Tool call'
    // The registry entry contributes the icon (friendly built-in icons, data-tool icons); fall back to
    // the generic wrench only when the renderer is mounted without a resolved entry.
    const headerIcon = icon ?? <IconWrench className="text-base" />
    const contentText = message.content.length > 0 ? renderContentBlocks(message.content) : ''
    const outputText =
        message.rawOutput !== undefined && message.rawOutput !== null ? JSON.stringify(message.rawOutput, null, 2) : ''

    const details = (
        <div className="flex flex-col gap-1">
            <ActivityToggleSection title="Input">
                <CodeSnippet language={Language.JSON} compact>
                    {JSON.stringify(message.innerInput ?? message.rawInput, null, 2)}
                </CodeSnippet>
            </ActivityToggleSection>
            {contentText && (
                <ActivityToggleSection title="Output">
                    <CodeSnippet language={Language.Text} compact>
                        {contentText}
                    </CodeSnippet>
                </ActivityToggleSection>
            )}
            {outputText && (
                <ActivityToggleSection title="Raw output">
                    <CodeSnippet language={Language.JSON} compact>
                        {outputText}
                    </CodeSnippet>
                </ActivityToggleSection>
            )}
        </div>
    )

    const hasFailureMessage = message.status === 'failed' && !!message.error?.message
    const activityBody =
        hasFailureMessage || children ? (
            <div className="flex flex-col gap-2">
                {hasFailureMessage && <div className="text-danger text-sm">{message.error?.message}</div>}
                {children}
            </div>
        ) : null

    return (
        <Activity
            id={message.id}
            title={<span className="font-medium text-default">{headerLabel}</span>}
            status={message.status}
            icon={headerIcon}
            showProgressIcon
            failedIcon={<IconWarning className="text-danger size-3" />}
            details={details}
        >
            <SandboxToolMessageBubble>{activityBody}</SandboxToolMessageBubble>
        </Activity>
    )
}
