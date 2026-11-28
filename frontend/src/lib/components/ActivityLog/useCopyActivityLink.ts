import { router } from 'kea-router'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ACTIVITY_SEARCH_PARAM } from './activityLogLogic'

/** Copies a link to the current page that opens and highlights the activity with this id. */
export function useCopyActivityLink(id?: string): () => void {
    return (): void => {
        if (!id) {
            return
        }
        const { pathname, search, hash } = router.values.currentLocation
        const url = new URL(pathname, window.location.origin)
        url.search = search || ''
        url.hash = hash || ''
        url.searchParams.delete(ACTIVITY_SEARCH_PARAM)
        url.searchParams.set(ACTIVITY_SEARCH_PARAM, id)
        void copyToClipboard(url.toString(), 'activity link')
    }
}
