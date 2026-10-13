import posthog from 'posthog-js'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag } from '@posthog/lemon-ui'

import { uuid } from 'lib/utils/dom'

import { JSONEditor } from '../components/JSONEditor'
import type { MessageToolCall } from './llmPlaygroundPromptsLogic'

/** Editable list of an assistant message's tool calls: name, call id, and JSON arguments. */
export function MessageToolCallsEditor({
    toolCalls,
    onChange,
}: {
    toolCalls: MessageToolCall[]
    onChange: (toolCalls: MessageToolCall[]) => void
}): JSX.Element {
    const updateToolCall = (index: number, payload: Partial<MessageToolCall>): void => {
        onChange(toolCalls.map((toolCall, i) => (i === index ? { ...toolCall, ...payload } : toolCall)))
    }

    return (
        <div className="mt-2 space-y-2">
            {toolCalls.map((toolCall, index) => (
                <div key={index} className="border rounded p-2 space-y-2">
                    <div className="flex items-center gap-2">
                        <LemonTag type="default" size="small">
                            Tool call
                        </LemonTag>
                        <LemonInput
                            size="small"
                            className="flex-1"
                            placeholder="Tool name"
                            value={toolCall.name}
                            onChange={(value) => updateToolCall(index, { name: value })}
                            data-attr="llma-playground-tool-call-name"
                        />
                        <LemonInput
                            size="small"
                            className="flex-1 font-mono"
                            placeholder="Call id"
                            value={toolCall.id}
                            onChange={(value) => updateToolCall(index, { id: value })}
                            data-attr="llma-playground-tool-call-id"
                        />
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            noPadding
                            tooltip="Delete tool call"
                            onClick={() => {
                                posthog.capture('llma playground tool call removed')
                                onChange(toolCalls.filter((_, i) => i !== index))
                            }}
                            data-attr="llma-playground-remove-tool-call"
                        />
                    </div>
                    <div className="border rounded">
                        <JSONEditor
                            value={toolCall.arguments}
                            onChange={(value) => updateToolCall(index, { arguments: value ?? '' })}
                            defaultNumberOfLines={2}
                            maxNumberOfLines={12}
                        />
                    </div>
                </div>
            ))}
            <LemonButton
                type="secondary"
                size="xsmall"
                icon={<IconPlus />}
                onClick={() => {
                    posthog.capture('llma playground tool call added')
                    onChange([...toolCalls, { id: `call_${uuid().slice(0, 8)}`, name: '', arguments: '{}' }])
                }}
                data-attr="llma-playground-add-tool-call"
            >
                Tool call
            </LemonButton>
        </div>
    )
}
