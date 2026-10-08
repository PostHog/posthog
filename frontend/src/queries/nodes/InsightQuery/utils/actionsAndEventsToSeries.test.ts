import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'

import { NodeKind } from '~/queries/schema/schema-general'
import { ActionFilter, BaseMathType, FunnelDatawarehouseFilter, LifecycleDatawarehouseFilter } from '~/types'

import { actionsAndEventsToSeries } from './actionsAndEventsToSeries'

describe('actionsAndEventsToSeries', () => {
    it('sorts series by order', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', order: 1, name: 'item2', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item3' },
        ]

        const result = actionsAndEventsToSeries({ actions, events }, false, MathAvailability.None)

        expect(result[0].name).toEqual('item1')
        expect(result[1].name).toEqual('item2')
        expect(result[2].name).toEqual('item3')
    })

    it('sorts elements without order first', () => {
        const actions: ActionFilter[] = [{ type: 'actions', id: '1', name: 'itemWithOrder', math: 'total' }]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 0, name: 'item1' },
            { id: '$autocapture', type: 'events', order: 2, name: 'item2' },
        ]

        const result = actionsAndEventsToSeries({ actions, events }, false, MathAvailability.None)

        expect(result[0].name).toEqual('itemWithOrder')
        expect(result[1].name).toEqual('item1')
        expect(result[2].name).toEqual('item2')
    })

    it('assumes typeless series is an event series', () => {
        const events: ActionFilter[] = [{ id: '$pageview', order: 0, name: 'item1' } as any]

        const result = actionsAndEventsToSeries({ events }, false, MathAvailability.None)

        expect(result[0].kind).toEqual(NodeKind.EventsNode)
    })

    it('converts funnels math types', () => {
        const actions: ActionFilter[] = [
            { type: 'actions', id: '1', order: 0, name: 'item1', math: 'total' },
            { type: 'actions', id: '1', order: 1, name: 'item2', math: 'first_time_for_user' },
        ]
        const events: ActionFilter[] = [
            { id: '$pageview', type: 'events', order: 2, name: 'item3', math: 'total' },
            { id: '$autocapture', type: 'events', order: 3, name: 'item4', math: 'first_time_for_user' },
        ]

        const result = actionsAndEventsToSeries({ events, actions }, false, MathAvailability.FunnelsOnly)

        expect(result).toEqual([
            {
                kind: NodeKind.ActionsNode,
                id: '1',
                name: 'item1',
            },
            {
                kind: NodeKind.ActionsNode,
                id: '1',
                name: 'item2',
                math: BaseMathType.FirstTimeForUser,
            },
            {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: 'item3',
            },
            {
                kind: NodeKind.EventsNode,
                event: '$autocapture',
                name: 'item4',
                math: BaseMathType.FirstTimeForUser,
            },
        ])
    })

    it('converts lifecycle data warehouse series to lifecycle nodes', () => {
        const data_warehouse: LifecycleDatawarehouseFilter[] = [
            {
                type: 'data_warehouse',
                id: 'warehouse_orders',
                order: 0,
                name: 'Orders',
                table_name: 'warehouse_orders',
                timestamp_field: 'timestamp',
                aggregation_target_field: 'order_id',
                created_at_field: 'created_at',
            },
        ]

        const result = actionsAndEventsToSeries(
            { data_warehouse },
            true,
            MathAvailability.None,
            NodeKind.LifecycleDataWarehouseNode
        )

        expect(result).toEqual([
            {
                kind: NodeKind.LifecycleDataWarehouseNode,
                id: 'warehouse_orders',
                name: 'Orders',
                table_name: 'warehouse_orders',
                timestamp_field: 'timestamp',
                aggregation_target_field: 'order_id',
                created_at_field: 'created_at',
            },
        ])
    })

    it('converts funnels data warehouse series to funnels nodes', () => {
        const data_warehouse: FunnelDatawarehouseFilter[] = [
            {
                type: 'data_warehouse' as const,
                id: 'warehouse_orders',
                order: 0,
                name: 'Orders',
                table_name: 'warehouse_orders',
                timestamp_field: 'timestamp',
                id_field: 'id',
                aggregation_target_field: 'person_id',
            },
        ]

        const result = actionsAndEventsToSeries(
            { data_warehouse },
            true,
            MathAvailability.FunnelsOnly,
            NodeKind.FunnelsDataWarehouseNode
        )

        expect(result).toEqual([
            {
                kind: NodeKind.FunnelsDataWarehouseNode,
                id: 'warehouse_orders',
                name: 'Orders',
                table_name: 'warehouse_orders',
                timestamp_field: 'timestamp',
                id_field: 'id',
                aggregation_target_field: 'person_id',
            },
        ])
    })
})
