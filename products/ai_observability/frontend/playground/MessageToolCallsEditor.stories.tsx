import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { MessageToolCall } from './llmPlaygroundPromptsLogic'
import { MessageToolCallsEditor } from './MessageToolCallsEditor'

const meta: Meta<typeof MessageToolCallsEditor> = {
    title: 'Components/Message Tool Calls Editor',
    component: MessageToolCallsEditor,
}
export default meta
type Story = StoryObj<typeof MessageToolCallsEditor>

export const EditableToolCalls: Story = {
    render: function Render() {
        const [toolCalls, setToolCalls] = useState<MessageToolCall[]>([
            { id: 'call_1a2b3c4d', name: 'get_weather', arguments: '{\n  "location": "San Francisco, CA"\n}' },
        ])
        return (
            <div className="max-w-150">
                <MessageToolCallsEditor toolCalls={toolCalls} onChange={setToolCalls} />
            </div>
        )
    },
}
