import { IconMarkdown, IconMarkdownFilled } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { JSONViewer } from 'lib/components/JSONViewer'
import { IconArrowDown, IconArrowUp, IconExclamation } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { useState } from 'react'

import { EventType } from '~/types'

import { CompatMessage } from '../types'
import { normalizeMessages } from '../utils'

export function ConversationMessagesDisplay({
    eventProperties,
}: {
    eventProperties: EventType['properties']
}): JSX.Element {
    const input = normalizeMessages(eventProperties.$ai_input)
    const output = normalizeMessages(eventProperties.$ai_output_choices || eventProperties.$ai_output)
    const { $ai_http_status: httpStatus } = eventProperties

    return (
        <div className="bg-bg-light rounded-lg border p-2">
            <h4 className="flex items-center gap-x-1.5 text-xs font-semibold mb-2">
                <IconArrowUp className="text-base" />
                Input
            </h4>
            {input?.map((message, i) => (
                <>
                    <MessageDisplay key={i} message={message} />
                    {i < input.length - 1 && <div className="border-l ml-2 h-2" /> /* Spacer connecting messages */}
                </>
            )) || (
                <div className="rounded border text-default p-2 italic bg-[var(--background-danger-subtle)]">
                    Missing input
                </div>
            )}
            <h4 className="flex items-center gap-x-1.5 text-xs font-semibold my-2">
                <IconArrowDown className="text-base" />
                Output{output && output.length > 1 ? ' (multiple choices)' : ''}
            </h4>
            {output?.map((message, i) => (
                <>
                    <MessageDisplay key={i} message={message} isOutput />
                    {i < output.length - 1 && (
                        <div className="border-l ml-4 h-2" /> /* Spacer connecting messages visually */
                    )}
                </>
            )) || (
                <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--background-danger-subtle)]">
                    <IconExclamation className="text-base" />
                    {httpStatus ? `Generation failed with HTTP status ${httpStatus}` : 'Missing output'}
                </div>
            )}
        </div>
    )
}

function MessageDisplay({ message, isOutput }: { message: CompatMessage; isOutput?: boolean }): JSX.Element {
    const [isRenderingMarkdown, setIsRenderingMarkdown] = useState(!!message.content)

    const { role, content, ...additionalKwargs } = message
    const additionalKwargsEntries = Object.entries(additionalKwargs)

    return (
        <div
            className={clsx(
                'rounded border text-default',
                isOutput
                    ? 'bg-[var(--background-success-subtle)]'
                    : role === 'system'
                    ? 'bg-[var(--background-secondary)]'
                    : role === 'user'
                    ? 'bg-bg-light'
                    : 'bg-[var(--blue-50)] dark:bg-[var(--blue-800)]' // We don't have a semantic color using blue
            )}
        >
            <div className="flex items-center gap-1 w-full px-2 h-6 text-xs font-medium">
                <span className="grow">{role}</span>
                {content && (
                    <LemonButton
                        size="small"
                        noPadding
                        icon={isRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                        tooltip="Toggle Markdown rendering"
                        onClick={() => setIsRenderingMarkdown(!isRenderingMarkdown)}
                    />
                )}
                <CopyToClipboardInline iconSize="small" description="message content" explicitValue={content} />
            </div>
            {!!content && (
                <div className={clsx('p-2 whitespace-pre-wrap border-t', !isRenderingMarkdown && 'font-mono text-xs')}>
                    {isRenderingMarkdown ? <LemonMarkdown>{content}</LemonMarkdown> : content}
                </div>
            )}
            {!!additionalKwargsEntries && additionalKwargsEntries.length > 0 && (
                <div className="p-2 text-xs border-t">
                    {additionalKwargsEntries.map(
                        ([key, value]) =>
                            typeof value !== 'undefined' && (
                                <JSONViewer
                                    key={key}
                                    name={key}
                                    src={value}
                                    collapseStringsAfterLength={200}
                                    displayDataTypes={false}
                                    // shouldCollapse limits depth shown at first. `> 4` is chosen so that we do show
                                    // function arguments in `tool_calls`, but if an argument is an object,
                                    // its child objects are collapsed by default
                                    shouldCollapse={({ namespace }) => namespace.length > 5}
                                />
                            )
                    )}
                </div>
            )}
        </div>
    )
}
