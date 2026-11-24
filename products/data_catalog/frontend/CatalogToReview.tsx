import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { QuillSuggestionsBanner } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsBanner'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { CatalogToReviewList } from './CatalogToReviewList'
import { usageLogic } from './usageLogic'

interface SuggestedMetricsProps {
    suggestedMetricCount: number
}

function CatalogToReviewWithSuggestions({ suggestedMetricCount }: SuggestedMetricsProps): JSX.Element | null {
    const { stripState } = useValues(warehouseSuggestionsLogic)

    return (
        <CatalogToReviewList
            suggestedMetricCount={suggestedMetricCount}
            suggestionsBanner={
                stripState === 'active' ? (
                    <QuillSuggestionsBanner reviewTo={urls.dataCatalog('suggestions')} />
                ) : undefined
            }
        />
    )
}

function CatalogToReviewRows({ suggestedMetricCount }: SuggestedMetricsProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return <CatalogToReviewList suggestedMetricCount={suggestedMetricCount} />
    }

    return <CatalogToReviewWithSuggestions suggestedMetricCount={suggestedMetricCount} />
}

function CatalogToReviewWithSuggestedMetrics(): JSX.Element | null {
    const { proposedRows } = useValues(usageLogic)

    return <CatalogToReviewRows suggestedMetricCount={proposedRows.length} />
}

export function CatalogToReview(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    // The usage logic loads the latest scan when it mounts, so it mounts only when the usage flag is on.
    if (!featureFlags[FEATURE_FLAGS.DATA_CATALOG_USAGE]) {
        return <CatalogToReviewRows suggestedMetricCount={0} />
    }

    return <CatalogToReviewWithSuggestedMetrics />
}
