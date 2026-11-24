import { urls } from 'scenes/urls'

import { entityListLogic } from '../lists/entityListLogic'
import type { ListFiltersLogicProps } from '../lists/listFiltersLogic'
import { ToolDetail, ToolRow, loadToolDetail, loadToolRows } from './toolsQueries'

export const TOOLS_LIST_FILTERS: ListFiltersLogicProps = { listId: 'tools', path: urls.aiObservabilityTools() }

// pinned: `tool` holds the open tool, which shared links read
export const toolsListLogic = entityListLogic<ToolRow, ToolDetail>({
    listId: 'tools',
    path: TOOLS_LIST_FILTERS.path,
    param: 'tool',
    rowKey: (row) => row.tool,
    loadRows: loadToolRows,
    loadDetail: loadToolDetail,
})
