export const DUPLICATE_ACTION_NAME_ERROR = 'An action with this name already exists. Pick a different name.'

/** The action being edited may keep its own name. */
export function isActionNameTaken(
    name: string,
    actions: { id: number; name: string | null }[],
    selectedActionId: number | 'new' | null
): boolean {
    return actions.some((action) => action.name === name && action.id !== selectedActionId)
}

/** Matches the backend's unique-name validation error body. */
export function isDuplicateActionNameResponse(body: unknown): boolean {
    if (!body || typeof body !== 'object') {
        return false
    }
    const { attr, code } = body as Record<string, unknown>
    return attr === 'name' && code === 'unique'
}
