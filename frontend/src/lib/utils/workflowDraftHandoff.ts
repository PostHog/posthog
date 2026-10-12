import { z } from 'zod'

import { uuid } from 'lib/utils/dom'

export const WORKFLOW_BRIEF_MAX_LENGTH = 4000
// pinned: URL search param naming the stored brief an AI workflow builder entry takes
export const WORKFLOW_BRIEF_HANDOFF_PARAM = 'handoff'

const storageKey = (projectId: number): string => `posthog-workflow-draft-brief:${projectId}`

const workflowDraftBriefSchema = z.object({
    prompt: z
        .string()
        .max(WORKFLOW_BRIEF_MAX_LENGTH)
        .refine((prompt) => !!prompt.trim()),
    eventProperties: z.object({
        source: z.literal('ai_turn_suggestion'),
        task_id: z.string(),
        turn_index: z.number().int(),
        team_id: z.string(),
    }),
})

const storedWorkflowDraftBriefSchema = workflowDraftBriefSchema.extend({ handoffId: z.string() })

export type WorkflowDraftBrief = z.infer<typeof workflowDraftBriefSchema>
export type WorkflowDraftEventProperties = WorkflowDraftBrief['eventProperties']

export function isValidWorkflowBrief(prompt: string): boolean {
    return workflowDraftBriefSchema.shape.prompt.safeParse(prompt).success
}

/** Returns the handoff id the builder entry URL must carry to take this brief. */
export function storeWorkflowDraftBrief(
    projectId: number,
    prompt: string,
    eventProperties: WorkflowDraftEventProperties
): string {
    const handoffId = uuid()
    const stored = storedWorkflowDraftBriefSchema.parse({ handoffId, prompt, eventProperties })
    sessionStorage.setItem(storageKey(projectId), JSON.stringify(stored))
    return handoffId
}

/** Any entry clears the stored brief, so a brief its own entry never took cannot reach a later workflow. */
export function consumeWorkflowDraftBrief(projectId: number, handoffId: unknown): WorkflowDraftBrief | null {
    const key = storageKey(projectId)
    const stored = sessionStorage.getItem(key)
    sessionStorage.removeItem(key)
    if (!stored || typeof handoffId !== 'string') {
        return null
    }
    try {
        const parsed = storedWorkflowDraftBriefSchema.safeParse(JSON.parse(stored))
        if (!parsed.success || parsed.data.handoffId !== handoffId) {
            return null
        }
        return { prompt: parsed.data.prompt, eventProperties: parsed.data.eventProperties }
    } catch {
        return null
    }
}
