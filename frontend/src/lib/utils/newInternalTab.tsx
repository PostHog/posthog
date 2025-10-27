import { getContext } from 'kea'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

export function newInternalTab(path?: string): void {
    getContext().store.dispatch({
        type: NEW_INTERNAL_TAB,
        payload: { path },
    })
}
