import { expectLogic } from 'kea-test-utils'

import { PEOPLE_LIST_CONTEXT_KEY, PEOPLE_LIST_DEFAULT_QUERY } from 'scenes/persons/personsSceneLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { TableViewSupportedQueryType, tableViewLogic } from './tableViewLogic'

describe('tableViewLogic', () => {
    let logic: ReturnType<typeof tableViewLogic.build>

    const defaultQuery = PEOPLE_LIST_DEFAULT_QUERY.source as TableViewSupportedQueryType

    const filteredQuery = {
        ...defaultQuery,
        properties: [{ type: PropertyFilterType.Person, key: 'email', operator: PropertyOperator.IsSet, value: null }],
    } as TableViewSupportedQueryType

    const savedView = {
        id: 'view-1',
        name: 'My view',
        context_key: PEOPLE_LIST_CONTEXT_KEY,
        columns: defaultQuery.select,
        filters: filteredQuery.properties,
        order_by: [],
    } as unknown as ColumnConfigurationApi

    const mountWithView = (query: TableViewSupportedQueryType): void => {
        logic = tableViewLogic({ contextKey: PEOPLE_LIST_CONTEXT_KEY, query, setQuery: () => {} })
        logic.mount()
        logic.actions.setCurrentView(savedView)
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('forgets the active view when the user clears filters back to the default query', async () => {
        mountWithView(filteredQuery)
        await expectLogic(logic).toMatchValues({ currentView: savedView })

        // Clearing filters resets the query to the default; the stale view must not survive to be
        // silently re-applied from localStorage on the next mount.
        tableViewLogic({ contextKey: PEOPLE_LIST_CONTEXT_KEY, query: defaultQuery, setQuery: () => {} })
        await expectLogic(logic).toMatchValues({ currentView: null })
    })

    it('keeps the active view when filters change but do not clear', async () => {
        mountWithView(filteredQuery)

        const otherFilteredQuery = {
            ...defaultQuery,
            properties: [
                { type: PropertyFilterType.Person, key: 'name', operator: PropertyOperator.IsSet, value: null },
            ],
        } as TableViewSupportedQueryType
        tableViewLogic({ contextKey: PEOPLE_LIST_CONTEXT_KEY, query: otherFilteredQuery, setQuery: () => {} })
        await expectLogic(logic).toMatchValues({ currentView: savedView })
    })

    it('drops a persisted view that no longer exists once views load', async () => {
        mountWithView(filteredQuery)

        logic.actions.loadViewsSuccess([{ ...savedView, id: 'a-different-view' }] as ColumnConfigurationApi[])
        await expectLogic(logic).toMatchValues({ currentView: null })
    })
})
