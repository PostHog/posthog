import { QuickFilter, QuickFilterAutoDiscoveryConfig, QuickFilterOption } from '~/types'

export function isManualQuickFilter(
    filter: QuickFilter | null
): filter is QuickFilter & { options: QuickFilterOption[] } {
    return filter?.type === 'manual-options'
}

export function isAutoDiscoveryQuickFilter(
    filter: QuickFilter | null
): filter is QuickFilter & { options: QuickFilterAutoDiscoveryConfig } {
    return filter?.type === 'auto-discovery'
}
