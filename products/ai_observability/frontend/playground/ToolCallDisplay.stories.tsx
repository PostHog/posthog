import { Meta, StoryObj } from '@storybook/react'

import { ToolCallDisplay } from './ToolCallDisplay'

const meta: Meta<typeof ToolCallDisplay> = {
    title: 'Components/Tool Call Display',
    component: ToolCallDisplay,
}
export default meta
type Story = StoryObj<typeof ToolCallDisplay>

export const StreamedToolCall: Story = {
    render: function Render() {
        return (
            <div className="max-w-150">
                <ToolCallDisplay
                    toolCall={{
                        id: 'call_1a2b3c4d',
                        name: 'get_weather',
                        arguments: '{"location": "San Francisco, CA", "unit": "celsius"}',
                    }}
                />
            </div>
        )
    },
}
