import { BindLogic, useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'

import { QuillCertificationSuggestionsDialogs } from 'products/warehouse_suggestions/frontend/components/QuillCertificationSuggestionsDialogs'
import { certificationSummaryText } from 'products/warehouse_suggestions/frontend/suggestionCopy'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { CatalogToReviewList } from './CatalogToReviewList'
import { certificationsLogic } from './certificationsLogic'

function CatalogToReviewWithSuggestions(): JSX.Element {
    const { stripState, surfaceSuggestions } = useValues(warehouseSuggestionsLogic)
    const { openReview } = useActions(warehouseSuggestionsLogic)
    const count = stripState === 'active' ? surfaceSuggestions.length : 0

    return (
        <>
            <CatalogToReviewList
                suggestionsItem={{
                    key: 'certification-suggestions',
                    count,
                    title: pluralize(count, 'certification suggestion'),
                    description: certificationSummaryText(surfaceSuggestions),
                    onReview: () => openReview(),
                }}
            />
            <QuillCertificationSuggestionsDialogs />
        </>
    )
}

export function CatalogToReview(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { suggestionAccepted } = useActions(certificationsLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return <CatalogToReviewList />
    }

    return (
        <BindLogic
            logic={warehouseSuggestionsLogic}
            props={{ surface: 'catalog', placement: 'overview', onAccepted: () => suggestionAccepted() }}
        >
            <CatalogToReviewWithSuggestions />
        </BindLogic>
    )
}
