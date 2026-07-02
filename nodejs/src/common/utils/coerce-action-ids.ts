/**
 * posthog_action.id is BIGINT, which pg returns as string.
 * Coerce id and team_id back to number since action IDs are well within safe integer range.
 */
export function coerceActionIds<T extends { id: unknown; team_id: unknown }>(action: T): T {
    action.id = Number(action.id)
    action.team_id = Number(action.team_id)
    return action
}
