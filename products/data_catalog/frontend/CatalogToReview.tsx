import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { QuillSuggestionsBanner } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsBanner'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { CatalogToReviewList } from './CatalogToReviewList'

function CatalogToReviewWithSuggestions(): JSX.Element | null {
    const { stripState } = useValues(warehouseSuggestionsLogic)

    return (
        <CatalogToReviewList
            suggestionsBanner={
                stripState === 'active' ? (
                    <QuillSuggestionsBanner reviewTo={urls.dataCatalog('suggestions')} />
                ) : undefined
            }
        />
    )
}

export function CatalogToReview(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return <CatalogToReviewList />
    }

    return <CatalogToReviewWithSuggestions />
}
