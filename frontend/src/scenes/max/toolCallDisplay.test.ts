import { EnhancedToolCall } from './max-constants'
import { getToolCallDescriptionAndWidgetDef } from './toolCallDisplay'

function toolCall(name: string, status: string): EnhancedToolCall {
    return { id: 'call-1', name, args: {}, status } as unknown as EnhancedToolCall
}

describe('getToolCallDescriptionAndWidgetDef', () => {
    it.each(['in_progress', 'completed'])('keeps an unmapped tool name out of the status line (%s)', (status) => {
        // The activity row shows this text, so a tool with no definition must not leak its identifier.
        const [description] = getToolCallDescriptionAndWidgetDef(toolCall('some_unmapped_tool', status), {})

        expect(description).not.toContain('some_unmapped_tool')
    })
})
