import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { MessageToolCall } from './llmPlaygroundPromptsLogic'
import { MessageToolCallsEditor } from './MessageToolCallsEditor'

const meta: Meta<typeof MessageToolCallsEditor> = {
    title: 'Components/Message Tool Calls Editor',
    component: MessageToolCallsEditor,
    parameters: {
        testOptions: {
            // Wait for the editor itself: `.monaco-editor` also matches Monaco's shared overflow root on
            // <body>, which exists before any editor mounts.
            waitForSelector: '.CodeEditor[data-editor-ready="true"]',
        },
    },
}
export default meta
type Story = StoryObj<typeof MessageToolCallsEditor>

export const EditableToolCalls: Story = {
    render: function Render() {
        const [toolCalls, setToolCalls] = useState<MessageToolCall[]>([
            { id: 'call_1a2b3c4d', name: 'get_weather', arguments: '{\n  "location": "San Francisco, CA"\n}' },
        ])
        return (
            // A fixed width, not max-w: the snapshot root shrink-wraps its content, so the editor would
            // take whatever width the root had at the moment it mounted.
            <div className="w-150">
                <MessageToolCallsEditor toolCalls={toolCalls} onChange={setToolCalls} />
            </div>
        )
    },
}
