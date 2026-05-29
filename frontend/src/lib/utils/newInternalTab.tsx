import { addProjectIdIfMissing } from 'lib/utils/router-utils'

export const NEW_INTERNAL_TAB = 'NEW_INTERNAL_TAB'

/**
 * Open a path in a new browser tab. Preserves project scoping for relative URLs.
 */
export function newInternalTab(path?: string, _source: 'internal_link' | 'unknown' = 'internal_link'): void {
    if (!path) {
        return
    }
    const isExternal = /^(https?:|mailto:)/.test(path)
    const href = isExternal ? path : addProjectIdIfMissing(path)
    window.open(href, '_blank', 'noopener,noreferrer')
}
