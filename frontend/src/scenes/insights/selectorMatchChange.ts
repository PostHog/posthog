import { isActionsNode } from '~/queries/utils'
import { ActionType } from '~/types'

/** Mirrors the verdict the action API returns as `selector_match_changed_steps`, which is
 * measured against real events because a selector matching across elements cannot be
 * recognized from its text. */
export function hasSelectorMatchChange(
    series: (Record<string, any> | null | undefined)[] | null | undefined,
    actionsById: Partial<Record<number | string, ActionType>>
): boolean {
    if (!series) {
        return false
    }
    return series.some((node) => {
        if (!isActionsNode(node)) {
            return false
        }
        return !!actionsById[node.id]?.selector_match_changed_steps?.length
    })
}
