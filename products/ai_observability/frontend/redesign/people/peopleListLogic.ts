import { urls } from 'scenes/urls'

import { entityListLogic } from '../lists/entityListLogic'
import type { ListFiltersLogicProps } from '../lists/listFiltersLogic'
import { PersonDetail, PersonRow, loadPersonDetail, loadPersonRows } from './peopleQueries'

export const PEOPLE_LIST_FILTERS: ListFiltersLogicProps = { listId: 'people', path: urls.aiObservabilityUsers() }

// pinned: `person` holds the open person's distinct ID, which shared links read
export const peopleListLogic = entityListLogic<PersonRow, PersonDetail>({
    listId: 'people',
    path: PEOPLE_LIST_FILTERS.path,
    param: 'person',
    rowKey: (row) => row.distinctId,
    loadRows: loadPersonRows,
    loadDetail: loadPersonDetail,
})
