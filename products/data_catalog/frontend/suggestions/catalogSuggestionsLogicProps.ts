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

export function catalogSuggestionsLogicProps(placement: SuggestionPlacement): WarehouseSuggestionsLogicProps {
    return { placement, onAccepted: reloadCatalogRows, onViewAccepted: openAcceptedSubject }
}
