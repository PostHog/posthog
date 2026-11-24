import { urls } from 'scenes/urls'

import { entityListLogic } from '../lists/entityListLogic'
import type { ListFiltersLogicProps } from '../lists/listFiltersLogic'
import { ErrorDetail, ErrorRow, loadErrorDetail, loadErrorRows } from './errorsQueries'

export const ERRORS_LIST_FILTERS: ListFiltersLogicProps = { listId: 'errors', path: urls.aiObservabilityErrors() }

// pinned: `error` holds the open error, which shared links read
export const errorsListLogic = entityListLogic<ErrorRow, ErrorDetail>({
    listId: 'errors',
    path: ERRORS_LIST_FILTERS.path,
    param: 'error',
    rowKey: (row) => row.error,
    loadRows: loadErrorRows,
    loadDetail: loadErrorDetail,
})
