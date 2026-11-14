import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { suggestionCountsText } from 'products/warehouse_suggestions/frontend/suggestionCopy'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { CatalogToReviewList } from './CatalogToReviewList'

function CatalogToReviewWithSuggestions(): JSX.Element {
    const { stripState, surfaceSuggestions } = useValues(warehouseSuggestionsLogic)
    const { reportReviewOpened } = useActions(warehouseSuggestionsLogic)
    const count = stripState === 'active' ? surfaceSuggestions.length : 0

    return (
        <CatalogToReviewList
            suggestionsItem={{
                key: 'certification-suggestions',
                count,
                title: pluralize(count, 'suggestion'),
                description: suggestionCountsText(surfaceSuggestions),
                href: urls.dataCatalog('suggestions'),
                onReview: () => reportReviewOpened(),
            }}
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
