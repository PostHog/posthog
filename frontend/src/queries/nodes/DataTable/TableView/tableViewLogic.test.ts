import { getQueryFromView } from './tableViewLogic'
import { TableViewSupportedQueryType } from './tableViewLogic'
import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'
import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyOperator } from '~/types'

describe('tableViewLogic - getQueryFromView', () => {
    const baseQuery: TableViewSupportedQueryType = {
        kind: NodeKind.EventsQuery,
        select: ['*'],
    } as any

    it('promotes exact event filter to scalar event field', () => {
        const view: ColumnConfigurationApi = {
            id: '1',
            context_key: 'test',
            filters: [
                { key: 'event', value: 'pageview', operator: PropertyOperator.Exact }
            ]
        } as any

        const result = getQueryFromView(baseQuery, view) as any
        expect(result.event).toEqual('pageview')
        expect(result.properties).toHaveLength(0)
    })

    it('keeps regex event filter in properties and does not promote', () => {
        const view: ColumnConfigurationApi = {
            id: '1',
            context_key: 'test',
            filters: [
                { key: 'event', value: 'page', operator: PropertyOperator.Regex }
            ]
        } as any

        const result = getQueryFromView(baseQuery, view) as any
        expect(result.event).toBeUndefined()
        expect(result.properties).toHaveLength(1)
        expect(result.properties[0]).toEqual({ key: 'event', value: 'page', operator: PropertyOperator.Regex })
    })

    it('picks the last exact filter (artificial filter simulation)', () => {
        const view: ColumnConfigurationApi = {
            id: '1',
            context_key: 'test',
            filters: [
                { key: 'event', value: 'manual_match', operator: PropertyOperator.Exact },
                { key: 'event', value: 'artificial_match', operator: PropertyOperator.Exact }
            ]
        } as any

        const result = getQueryFromView(baseQuery, view) as any
        expect(result.event).toEqual('artificial_match')
        expect(result.properties).toHaveLength(0)
    })
    
    it('promotes In events filter to scalar events field', () => {
        const view: ColumnConfigurationApi = {
            id: '1',
            context_key: 'test',
            filters: [
                { key: 'events', value: ['pageview', 'click'], operator: PropertyOperator.In }
            ]
        } as any

        const result = getQueryFromView(baseQuery, view) as any
        expect(result.events).toEqual(['pageview', 'click'])
        expect(result.properties).toHaveLength(0)
    })

    it('keeps filters without an operator in properties', () => {
        const view: ColumnConfigurationApi = {
            id: '1',
            context_key: 'test',
            filters: [
                { key: 'something_else', value: 'value' } as any
            ]
        } as any

        const result = getQueryFromView(baseQuery, view) as any
        expect(result.properties).toHaveLength(1)
        expect(result.properties[0].key).toEqual('something_else')
    })
})
