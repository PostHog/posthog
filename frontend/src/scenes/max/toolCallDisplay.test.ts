import { EnhancedToolCall } from './max-constants'
import { getToolCallDescriptionAndWidgetDef } from './toolCallDisplay'

describe('getToolCallDescriptionAndWidgetDef', () => {
    it.each(['in_progress', 'completed'])('keeps an unmapped tool name out of the status line (%s)', (status) => {
        // The activity row shows this text, so a tool with no definition must not leak its identifier.
        const toolCall = { id: 'call-1', name: 'some_unmapped_tool', args: {}, status } as unknown as EnhancedToolCall

        const [description] = getToolCallDescriptionAndWidgetDef(toolCall, {})

        expect(description).not.toContain('some_unmapped_tool')
    })
})
