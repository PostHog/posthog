import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { countOf } from 'products/warehouse_suggestions/frontend/suggestionCopy'
import {
    BulkAction,
    warehouseSuggestionsSectionLogic,
} from 'products/warehouse_suggestions/frontend/warehouseSuggestionsSectionLogic'

import { CatalogBulkBar } from '../components/CatalogBulkBar'

const BUSY_REASON = 'Another bulk action is running'

export function CatalogSuggestionsBulkBar(): JSX.Element {
    const { selectedSuggestions, bulkActionRunning } = useValues(warehouseSuggestionsSectionLogic)
    const { openBulkAccept, openBulkDismiss, assignSelectedToMe, clearSelection } = useActions(
        warehouseSuggestionsSectionLogic
    )
    const busyReason = (action: BulkAction): string | undefined =>
        bulkActionRunning && bulkActionRunning !== action ? BUSY_REASON : undefined

    return (
        <CatalogBulkBar
            selectedLabel={`${countOf(selectedSuggestions.length, 'suggestion', 'suggestions')} selected`}
            onClear={clearSelection}
            dataAttr="data-catalog-suggestions-bulk-bar"
        >
            <Button
                variant="primary"
                size="sm"
                loading={bulkActionRunning === 'accept'}
                disabledReason={busyReason('accept')}
                onClick={openBulkAccept}
                data-attr="data-catalog-suggestions-bulk-accept"
            >
                Approve
            </Button>
            <Button
                variant="outline"
                size="sm"
                loading={bulkActionRunning === 'dismiss'}
                disabledReason={busyReason('dismiss')}
                onClick={openBulkDismiss}
                data-attr="data-catalog-suggestions-bulk-dismiss"
            >
                Dismiss
            </Button>
            <Button
                variant="outline"
                size="sm"
                loading={bulkActionRunning === 'assign'}
                disabledReason={busyReason('assign')}
                onClick={assignSelectedToMe}
                data-attr="data-catalog-suggestions-bulk-assign-me"
            >
                Assign to me
            </Button>
        </CatalogBulkBar>
    )
}
