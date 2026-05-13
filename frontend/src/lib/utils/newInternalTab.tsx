import { router } from 'kea-router'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

export function newInternalTab(path?: string): void {
    if (path) {
        router.actions.push(path)
    }
}
