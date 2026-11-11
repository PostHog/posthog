import { BindLogic, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { QuillSuggestionsBanner } from 'products/warehouse_suggestions/frontend/components/QuillSuggestionsBanner'
import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { catalogSuggestionsLogicProps } from '../suggestions/catalogSuggestionsLogicProps'

function ActiveSuggestionsBanner(): JSX.Element | null {
    const { stripState } = useValues(warehouseSuggestionsLogic)
    return stripState === 'active' ? <QuillSuggestionsBanner reviewTo={urls.dataCatalog('suggestions')} /> : null
}

export function CatalogTablesSuggestions(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return null
    }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={catalogSuggestionsLogicProps('tables_tab')}>
            <ActiveSuggestionsBanner />
        </BindLogic>
    )
}
