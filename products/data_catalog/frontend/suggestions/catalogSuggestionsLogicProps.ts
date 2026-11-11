import { combineUrl, router } from 'kea-router'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { modelsOverviewLogic } from 'products/data_modeling/frontend/modelsOverviewLogic'
import type { WarehouseSuggestionApi } from 'products/warehouse_suggestions/frontend/generated/api.schemas'
import type {
    SuggestionPlacement,
    WarehouseSuggestionsLogicProps,
} from 'products/warehouse_suggestions/frontend/warehouseSuggestionsLogic'

import { TABLES_SEARCH_PARAM } from '../catalogTableRows'
import { certificationsLogic } from '../certificationsLogic'
import type { DataCatalogTab } from '../dataCatalogSceneLogic'

const PLACEMENT_FOR_TAB: Partial<Record<DataCatalogTab, SuggestionPlacement>> = {
    overview: 'overview',
    tables: 'tables_tab',
    suggestions: 'suggestions_section',
}

function reloadCatalogRows(): void {
    databaseTableListLogic.findMounted()?.actions.loadDatabase({ force: true })
    modelsOverviewLogic.findMounted()?.actions.loadNodes()
    modelsOverviewLogic.findMounted()?.actions.loadDataWarehouseSavedQueries()
    certificationsLogic.findMounted()?.actions.loadCertifications()
}

function openAcceptedSubject(suggestion: WarehouseSuggestionApi): void {
    router.actions.push(
        combineUrl(urls.dataCatalog('tables'), { [TABLES_SEARCH_PARAM]: suggestion.payload.subject_name }).url
    )
}

export function catalogSuggestionsLogicProps(activeTab: DataCatalogTab): WarehouseSuggestionsLogicProps {
    return {
        placement: PLACEMENT_FOR_TAB[activeTab],
        onAccepted: reloadCatalogRows,
        onViewAccepted: openAcceptedSubject,
    }
}
