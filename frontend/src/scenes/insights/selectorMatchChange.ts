import { isActionsNode } from '~/queries/utils'
import { ActionType } from '~/types'

export interface SelectorMatchChange {
    actionId: ActionType['id']
    actionName: string
    selectors: string[]
}

/** A selector matching across elements cannot be recognized from its text, so the verdict
 * comes from the action API, which measures it against real events. */
export function getSelectorMatchChanges(
    series: (Record<string, any> | null | undefined)[] | null | undefined,
    actionsById: Partial<Record<number | string, ActionType>>
): SelectorMatchChange[] {
    if (!series) {
        return []
    }
    const changes: SelectorMatchChange[] = []
    for (const node of series) {
        if (!isActionsNode(node)) {
            continue
        }
        const action = actionsById[node.id]
        const changedSteps = action?.selector_match_changed_steps
        // One action can carry several series, and the notice names it once.
        if (!action || !changedSteps?.length || changes.some((change) => change.actionId === action.id)) {
            continue
        }
        changes.push({
            actionId: action.id,
            actionName: action.name || 'Untitled action',
            selectors: changedSteps
                .map((stepIndex) => action.steps?.[stepIndex]?.selector)
                .filter((selector): selector is string => !!selector),
        })
    }
    return changes
}
