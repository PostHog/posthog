import { useValues } from 'kea'

import { Badge } from '@posthog/quill'

import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

export function CatalogSuggestionsCountBadge(): JSX.Element | null {
    const { stripState, surfaceSuggestions } = useValues(warehouseSuggestionsLogic)
    return stripState === 'active' ? <Badge>{surfaceSuggestions.length}</Badge> : null
}
