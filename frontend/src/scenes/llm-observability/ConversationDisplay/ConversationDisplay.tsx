import { IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { lowercaseFirstLetter } from 'lib/utils'
import React, { useState } from 'react'

import { EventType } from '~/types'

interface CompletionMessage {
    /** Almost certainly one of: `user`, `assistant`, `system` */
    role: string
    content: string
    /** E.g. tool calls. */
    additional_kwargs?: Record<string, any> | null
}

type AIInput = CompletionMessage[]
type AIOutput = { choices: CompletionMessage[] }

function verifyInputShape(aiInput: any): AIInput | null {
    if (
        Array.isArray(aiInput) &&
        aiInput.every(
            (message: any) =>
                typeof message === 'object' &&
                'role' in message &&
                typeof message.role === 'string' &&
                'content' in message &&
                typeof message.content === 'string'
        )
    ) {
        return aiInput
    }
    return null
}

function verifyOutputShape(aiOutput: any): AIOutput | null {
    if (
        typeof aiOutput === 'object' &&
        'choices' in aiOutput &&
        Array.isArray(aiOutput.choices) &&
        aiOutput.choices.every(
            (message: any) =>
                typeof message === 'object' &&
                'role' in message &&
                typeof message.role === 'string' &&
                'content' in message &&
                typeof message.content === 'string'
        )
    ) {
        return aiOutput
    }
    return null
}

export function ConversationDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    const input = verifyInputShape(eventProperties.$ai_input)
    const output = verifyOutputShape(eventProperties.$ai_output)
    const {
        $ai_input_tokens: inputTokens,
        $ai_output_tokens: outputTokens,
        $ai_total_cost_usd: totalCostUsd,
        $ai_model: model,
        $ai_latency: latency,
        $ai_http_status: httpStatus,
    } = eventProperties

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-x-2">
                {typeof latency === 'number' && (
                    <MetadataTag label="Latency">{`${Math.round(latency * 10e2) / 10e2} s of latency`}</MetadataTag>
                )}
                {typeof inputTokens === 'number' && typeof outputTokens === 'number' && (
                    <MetadataTag label="Token usage">
                        {`${inputTokens} prompt tokens → ${outputTokens} completion tokens (∑ ${
                            inputTokens + outputTokens
                        })`}
                    </MetadataTag>
                )}
                {model && (
                    <MetadataTag label="Model" copyable>
                        {model}
                    </MetadataTag>
                )}
                {typeof totalCostUsd === 'number' && (
                    <MetadataTag label="Total generation cost" copyable>
                        {`$${Math.round(totalCostUsd * 10e6) / 10e6}`}
                    </MetadataTag>
                )}
            </div>
            <div className="bg-bg-light rounded-lg border p-2">
                <h4 className="flex items-center gap-x-1.5 text-xs font-semibold mb-2">
                    <IconArrowUp className="text-base" />
                    Input
                </h4>
                {input?.map(({ role, content, additional_kwargs }, i) => (
                    <>
                        <MessageDisplay key={i} role={role} additionalKwargs={additional_kwargs} content={content} />
                        {i < input.length - 1 && <div className="border-l ml-2 h-2" /> /* Spacer connecting messages */}
                    </>
                )) || <div className="rounded border text-default p-2 italic bg-[var(--red-50)]">Missing input</div>}
                <h4 className="flex items-center gap-x-1.5 text-xs font-semibold my-2">
                    <IconArrowDown className="text-base" />
                    Output{output && output.choices.length > 1 ? ' (multiple choices)' : ''}
                </h4>
                {output?.choices.map(({ role, content, additional_kwargs }, i) => (
                    <>
                        <MessageDisplay
                            key={i}
                            role={role}
                            content={content}
                            additionalKwargs={additional_kwargs}
                            isOutput
                        />
                        {i < output.choices.length - 1 && (
                            <div className="border-l ml-4 h-2" /> /* Spacer connecting messages visually */
                        )}
                    </>
                )) || (
                    <div className="rounded border text-default p-2 italic bg-[var(--red-50)]">
                        {httpStatus ? `Generation failed with HTTP status ${httpStatus}` : 'Missing output'}
                    </div>
                )}
            </div>
        </div>
    )
}

function MetadataTag({
    children,
    label,
    copyable = false,
}: {
    children: string
    label: string
    copyable?: boolean
}): JSX.Element {
    let wrappedChildren: React.ReactNode = children
    if (copyable) {
        wrappedChildren = (
            <CopyToClipboardInline iconSize="xsmall" description={lowercaseFirstLetter(label)} tooltipMessage={label}>
                {children}
            </CopyToClipboardInline>
        )
    } else {
        wrappedChildren = <Tooltip title={label}>{children}</Tooltip>
    }

    return <LemonTag className="bg-bg-light cursor-default">{wrappedChildren}</LemonTag>
}

function MessageDisplay({
    role,
    content,
    additionalKwargs,
    isOutput,
}: {
    role: CompletionMessage['role']
    content: CompletionMessage['content']
    additionalKwargs: CompletionMessage['additional_kwargs']
    isOutput?: boolean
}): JSX.Element {
    const [isRenderingMarkdown, setIsRenderingMarkdown] = useState(!!content)

    const additionalKwargsEntries = additionalKwargs && Object.entries(additionalKwargs)

    return (
        <div
            className={clsx(
                'rounded border text-default',
                isOutput
                    ? 'bg-[var(--green-50)]'
                    : role === 'system'
                    ? 'bg-[var(--neutral-50)]'
                    : role === 'user'
                    ? 'bg-bg-light'
                    : 'bg-[var(--blue-50)]'
            )}
        >
            <div className="flex items-center gap-2 w-full px-2 h-6 text-xs font-medium border-b">
                <span className="grow">{role}</span>
                {content && (
                    <LemonButton
                        size="small"
                        noPadding
                        icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                        onClick={() => setIsRenderingMarkdown(!isRenderingMarkdown)}
                    />
                )}
                <CopyToClipboardInline iconSize="small" description="message content" explicitValue={content} />
            </div>
            {!!content && (
                <div className={clsx('p-2 whitespace-pre-wrap', !isRenderingMarkdown && 'font-mono text-xs')}>
                    {isRenderingMarkdown ? <LemonMarkdown>{content}</LemonMarkdown> : content}
                </div>
            )}
            {!!additionalKwargsEntries && additionalKwargsEntries.length > 0 && (
                <div className={clsx('p-2 text-xs', !!content && 'border-t')}>
                    {additionalKwargsEntries.map(([key, value]) => (
                        <JSONViewer key={key} src={value} name={key} />
                    ))}
                </div>
            )}
        </div>
    )
}
