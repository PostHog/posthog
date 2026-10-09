const storageKey = (projectId: number): string => `posthog-workflow-draft-brief:${projectId}`

export function storeWorkflowDraftBrief(projectId: number, prompt: string): void {
    if (!prompt.trim() || prompt.length > 4000) {
        throw new Error('Add a workflow brief of up to 4,000 characters')
    }
    sessionStorage.setItem(storageKey(projectId), prompt)
}

export function consumeWorkflowDraftBrief(projectId: number): string | null {
    const key = storageKey(projectId)
    const prompt = sessionStorage.getItem(key)
    sessionStorage.removeItem(key)
    return prompt?.trim() && prompt.length <= 4000 ? prompt : null
}
