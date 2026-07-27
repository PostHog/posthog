import { TaskExecutionStatus } from '~/queries/schema/schema-assistant-messages'

import {
    EnhancedToolCall,
    RecordingsWidgetDef,
    SessionSummarizationWidgetDef,
    ToolRegistration,
    getToolDefinitionFromToolCall,
} from './max-constants'

export type ToolCallWidgetDef = RecordingsWidgetDef | SessionSummarizationWidgetDef

/**
 * Returns the human-readable description of a tool call plus the widget definition (data,
 * not JSX) for Thread to render. Lives outside Thread.tsx so logics can derive descriptions
 * without statically importing the thread component graph (monaco, Query, the message
 * widgets) into their chunk.
 */
export const getToolCallDescriptionAndWidgetDef = (
    toolCall: EnhancedToolCall,
    registeredToolMap: Record<string, ToolRegistration>
): [string, ToolCallWidgetDef | null] => {
    const commentary = toolCall.args.commentary as string
    const definition = getToolDefinitionFromToolCall(toolCall)
    let description = `${toolCall.status === TaskExecutionStatus.InProgress ? 'Executing' : 'Executed'} ${toolCall.name}`
    let widgetDef: ToolCallWidgetDef | null = null
    if (definition) {
        if (definition.displayFormatter) {
            const displayFormatterResult = definition.displayFormatter(toolCall, {
                registeredToolMap,
            })
            if (typeof displayFormatterResult === 'string') {
                description = displayFormatterResult
            } else {
                description = displayFormatterResult[0]
                widgetDef = displayFormatterResult[1] ?? null
            }
        }
        if (commentary) {
            description = commentary
        }
    }
    return [description, widgetDef]
}
