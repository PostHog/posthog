import { z } from 'zod'

const storageKey = (projectId: number): string => `posthog-workflow-draft-brief:${projectId}`

const workflowDraftBriefSchema = z.object({
    prompt: z
        .string()
        .max(4000)
        .refine((prompt) => !!prompt.trim()),
    eventProperties: z.object({
        source: z.literal('ai_turn_suggestion'),
        task_id: z.string(),
        turn_index: z.number().int(),
        team_id: z.string(),
    }),
})

export type WorkflowDraftBrief = z.infer<typeof workflowDraftBriefSchema>
export type WorkflowDraftEventProperties = WorkflowDraftBrief['eventProperties']

export function storeWorkflowDraftBrief(
    projectId: number,
    prompt: string,
    eventProperties: WorkflowDraftEventProperties
): void {
    if (!prompt.trim() || prompt.length > 4000) {
        throw new Error('Add a workflow brief of up to 4,000 characters')
    }
    sessionStorage.setItem(storageKey(projectId), JSON.stringify({ prompt, eventProperties }))
}

export function consumeWorkflowDraftBrief(projectId: number): WorkflowDraftBrief | null {
    const key = storageKey(projectId)
    const stored = sessionStorage.getItem(key)
    sessionStorage.removeItem(key)
    if (!stored) {
        return null
    }
    try {
        const brief = workflowDraftBriefSchema.safeParse(JSON.parse(stored))
        return brief.success && brief.data.eventProperties.team_id === String(projectId) ? brief.data : null
    } catch {
        return null
    }
}
