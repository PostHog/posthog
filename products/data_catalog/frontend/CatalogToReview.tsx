import { BindLogic, useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { QuillCertificationSuggestionsDialogs } from 'products/warehouse_suggestions/frontend/components/QuillCertificationSuggestionsDialogs'
import type { WarehouseSuggestionApi } from 'products/warehouse_suggestions/frontend/generated/api.schemas'
import { certificationSummaryText } from 'products/warehouse_suggestions/frontend/suggestionCopy'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { TABLES_SEARCH_PARAM } from './catalogTableRows'
import { CatalogToReviewList } from './CatalogToReviewList'
import { certificationsLogic } from './certificationsLogic'

function openAcceptedSubject(suggestion: WarehouseSuggestionApi): void {
    router.actions.push(
        combineUrl(urls.dataCatalog('tables'), { [TABLES_SEARCH_PARAM]: suggestion.payload.subject_name }).url
    )
}

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
            props={{
                surface: 'catalog',
                placement: 'overview',
                onAccepted: () => suggestionAccepted(),
                onViewAccepted: openAcceptedSubject,
            }}
        >
            <CatalogToReviewWithSuggestions />
        </BindLogic>
    )
}
