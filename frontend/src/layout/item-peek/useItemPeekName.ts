import { useSelector, useValues } from 'kea'

import { Breadcrumb } from '~/types'

import { itemPeekLogic } from './itemPeekLogic'

export function useItemPeekName(): string {
    const { loadedScene, peekProps, fallbackName } = useValues(itemPeekLogic)
    const breadcrumbName = useSelector((state): string | null => {
        const logic = loadedScene?.scene.logic
        if (!logic || !peekProps) {
            return null
        }
        try {
            const built = logic.build(peekProps)
            if (!('breadcrumbs' in built.selectors)) {
                return null
            }
            const breadcrumbs: Breadcrumb[] = built.selectors.breadcrumbs(state, peekProps)
            const name = breadcrumbs[breadcrumbs.length - 1]?.name
            return typeof name === 'string' && name ? name : null
        } catch {
            // The selector can throw before the scene logic has mounted or loaded its item.
            return null
        }
    })
    return breadcrumbName ?? fallbackName ?? 'Untitled'
}
