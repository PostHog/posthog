import type { ThreadItem, ToolInvocation } from 'products/posthog_ai/frontend/api/types'

const MAX_ACTIVITY_ITEMS = 3
const MAX_ACTIVITY_TEXT_LENGTH = 240

export interface GenUIGenerationActivityItem {
    active: boolean
    id: string
    text: string
}

function compactActivityText(value: string): string {
    const normalized = value.replace(/\s+/g, ' ').trim()
    if (normalized.length <= MAX_ACTIVITY_TEXT_LENGTH) {
        return normalized
    }
    return `…${normalized.slice(-(MAX_ACTIVITY_TEXT_LENGTH - 1))}`
}

function toolActivityText(invocation: ToolInvocation): string {
    if (invocation.title?.trim()) {
        return compactActivityText(invocation.title)
    }
    const command = typeof invocation.input.command === 'string' ? invocation.input.command.trim() : ''
    const commandTool = command.match(/^call\s+([^\s{]+)/)?.[1]
    if (commandTool) {
        return `Running ${commandTool}`
    }
    const toolName = invocation.rawToolName.trim() || 'tool'
    return `Using ${toolName}`
}

function threadItemActivity(
    item: ThreadItem,
    toolInvocations: Map<string, ToolInvocation>
): GenUIGenerationActivityItem | null {
    if (item.type === 'assistant_message' && item.text?.trim()) {
        return { active: item.complete !== true, id: item.id, text: compactActivityText(item.text) }
    }
    if (item.type === 'tool_invocation' && item.toolCallId) {
        const invocation = toolInvocations.get(item.toolCallId)
        if (!invocation) {
            return null
        }
        return {
            active: invocation.status === 'pending' || invocation.status === 'in_progress',
            id: item.id,
            text: toolActivityText(invocation),
        }
    }
    if (item.type === 'progress' && item.progressSteps?.length) {
        const activeStep = item.progressSteps.find((step) => step.status === 'in_progress')
        const latestStep = activeStep ?? item.progressSteps.at(-1)
        if (!latestStep) {
            return null
        }
        const text = latestStep.detail ? `${latestStep.label}: ${latestStep.detail}` : latestStep.label
        return { active: activeStep !== undefined, id: item.id, text: compactActivityText(text) }
    }
    if (item.type === 'task_notification' && item.summary?.trim()) {
        return { active: false, id: item.id, text: compactActivityText(item.summary) }
    }
    if (item.type === 'error' && item.errorMessage?.trim()) {
        return { active: false, id: item.id, text: compactActivityText(item.errorMessage) }
    }
    return null
}

export function selectGenUIGenerationActivity(
    threadItems: ThreadItem[],
    toolInvocations: Map<string, ToolInvocation>,
    currentProgress: string | null
): GenUIGenerationActivityItem[] {
    const items = threadItems
        .map((item) => threadItemActivity(item, toolInvocations))
        .filter((item): item is GenUIGenerationActivityItem => item !== null)

    if (currentProgress?.trim()) {
        items.push({ active: true, id: 'current-progress', text: compactActivityText(currentProgress) })
    }

    const uniqueItems: GenUIGenerationActivityItem[] = []
    for (const item of items) {
        const existingIndex = uniqueItems.findIndex((existing) => existing.text === item.text)
        if (existingIndex !== -1) {
            uniqueItems.splice(existingIndex, 1)
        }
        uniqueItems.push(item)
    }
    return uniqueItems.slice(-MAX_ACTIVITY_ITEMS)
}
