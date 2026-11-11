import { BindLogic, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { warehouseSuggestionsLogic } from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { dataCatalogSceneLogic } from '../dataCatalogSceneLogic'
import { catalogSuggestionsLogicProps } from './catalogSuggestionsLogicProps'

export function CatalogSuggestionsBinding({ children }: { children: JSX.Element }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(dataCatalogSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.WAREHOUSE_SUGGESTIONS]) {
        return children
    }
    return (
        <BindLogic logic={warehouseSuggestionsLogic} props={catalogSuggestionsLogicProps(activeTab)}>
            {children}
        </BindLogic>
    )
}
