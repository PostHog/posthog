import { expectLogic } from 'kea-test-utils'

import * as libUtils from 'lib/utils/dom'
import { entityFilterLogic, seriesNodeToGroupNode } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useMocks } from '~/mocks/jest'
import { AnyEntityNode, GroupNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { EntityTypes, FilterLogicalOperator, FilterType } from '~/types'

import { legacyFiltersToSeries } from '../legacyFilters'
import { SeriesNode } from '../seriesNode'
import { actionFilterGroupLogic } from './actionFilterGroupLogic'

const eventNode = (event: string, extra: Record<string, any> = {}): AnyEntityNode =>
    ({ kind: NodeKind.EventsNode, event, name: event, ...extra }) as AnyEntityNode

const groupNode = (nodes: AnyEntityNode[], extra: Record<string, any> = {}): GroupNode =>
    ({
        kind: NodeKind.GroupNode,
        name: nodes.map((n) => n.name).join(', '),
        operator: FilterLogicalOperator.Or,
        nodes,
        ...extra,
    }) as GroupNode

/** Mounts the editor on a fixed series, with deterministic row uuids. */
const mountLogic = (series: SeriesNode[], typeKey: string): ReturnType<typeof entityFilterLogic.build> => {
    let uuidCounter = 0
    ;(libUtils as any).uuid = jest.fn(() => `uuid-${uuidCounter++}`)

    const logic = entityFilterLogic({ onChange: jest.fn(), series, typeKey })
    logic.mount()
    return logic
}

describe('ActionFilterGroup - Combining and Splitting Events', () => {
    beforeEach(() => {
        ;(libUtils as any).uuid = jest.fn().mockReturnValue('test-uuid')
        useMocks({
            get: {
                '/api/projects/:team/actions/': {
                    results: [],
                },
                '/api/projects/:team/event_definitions/': {
                    results: [],
                },
            },
        })
        initKeaTests()
    })

    describe('seriesNodeToGroupNode', () => {
        it('converts a single event node to a group node', () => {
            const node = eventNode('$pageview')

            const group = seriesNodeToGroupNode(node)

            expect(group).toMatchObject({
                kind: NodeKind.GroupNode,
                operator: FilterLogicalOperator.Or,
            })
            expect(group.nodes).toHaveLength(1)
            expect(group.nodes[0]).toEqual(node)
        })

        it('preserves math properties at group level', () => {
            const group = seriesNodeToGroupNode(eventNode('$pageview', { math: 'dau', math_property: 'some_prop' }))

            expect(group).toMatchObject({
                math: 'dau',
                math_property: 'some_prop',
            })
        })

        it('handles action nodes', () => {
            const node = { kind: NodeKind.ActionsNode, id: 123, name: 'User Signup' } as AnyEntityNode

            const group = seriesNodeToGroupNode(node)

            expect(group.kind).toBe(NodeKind.GroupNode)
            expect(group.nodes).toContainEqual(node)
        })

        it('defaults to OR operator when creating group', () => {
            expect(seriesNodeToGroupNode(eventNode('$pageview')).operator).toBe(FilterLogicalOperator.Or)
        })

        it('does not carry custom_name from the child', () => {
            const group = seriesNodeToGroupNode(eventNode('$pageview', { custom_name: 'My renamed event' }))

            expect(group.custom_name).toBeUndefined()
            expect(group.kind).toBe(NodeKind.GroupNode)
            // the child retains its custom_name
            expect(group.nodes[0].custom_name).toBe('My renamed event')
        })
    })

    describe('splitGroup', () => {
        it('expands a group with two events back to individual series', () => {
            const logic = mountLogic([groupNode([eventNode('$pageview'), eventNode('$exception')])], 'split_two')

            logic.actions.splitGroup(0)

            expect(logic.values.series).toEqual([eventNode('$pageview'), eventNode('$exception')])
            logic.unmount()
        })

        it('maintains correct ordering when splitting into the middle of the list', () => {
            const logic = mountLogic(
                [
                    eventNode('$before'),
                    groupNode([eventNode('$pageview'), eventNode('$exception'), eventNode('$pageleave')]),
                    eventNode('$after'),
                ],
                'split_ordering'
            )

            logic.actions.splitGroup(1)

            expect(logic.values.series.map((node: any) => node.event)).toEqual([
                '$before',
                '$pageview',
                '$exception',
                '$pageleave',
                '$after',
            ])
            logic.unmount()
        })

        it('handles groups with a mix of events and actions', () => {
            const logic = mountLogic(
                [
                    groupNode([
                        eventNode('$pageview'),
                        { kind: NodeKind.ActionsNode, id: 123, name: 'User Signup' } as AnyEntityNode,
                    ]),
                ],
                'split_mixed'
            )

            logic.actions.splitGroup(0)

            expect(logic.values.series.map((node) => node.kind)).toEqual([NodeKind.EventsNode, NodeKind.ActionsNode])
            logic.unmount()
        })

        it('preserves properties when splitting', () => {
            const properties = [{ type: 'event', key: 'page_location', value: '/product', operator: 'exact' }]
            const logic = mountLogic([groupNode([eventNode('$pageview', { properties })])], 'split_properties')

            logic.actions.splitGroup(0)

            expect(logic.values.series[0].properties).toEqual(properties)
            logic.unmount()
        })

        it('does not leak the group custom_name to its children', () => {
            const logic = mountLogic(
                [
                    groupNode([eventNode('$pageview'), eventNode('$exception')], {
                        custom_name: 'My conversion events',
                    }),
                ],
                'split_custom_name'
            )

            logic.actions.splitGroup(0)

            expect(logic.values.series).toHaveLength(2)
            expect(logic.values.series[0].custom_name).toBeUndefined()
            expect(logic.values.series[1].custom_name).toBeUndefined()
            logic.unmount()
        })

        it('combining and splitting round-trips to the same series', () => {
            const original = eventNode('$pageview')
            const logic = mountLogic([original], 'round_trip')

            logic.actions.convertToGroup(0)
            expect(logic.values.series[0].kind).toBe(NodeKind.GroupNode)

            logic.actions.splitGroup(0)

            expect(logic.values.series).toHaveLength(1)
            expect(logic.values.series[0]).toEqual(original)
            logic.unmount()
        })

        it('handles an empty group', () => {
            const logic = mountLogic([groupNode([])], 'split_empty')

            logic.actions.splitGroup(0)

            expect(logic.values.series).toHaveLength(0)
            logic.unmount()
        })

        it('handles a single-item group', () => {
            const logic = mountLogic([groupNode([eventNode('$pageview')])], 'split_single')

            logic.actions.splitGroup(0)

            expect(logic.values.series).toEqual([eventNode('$pageview')])
            logic.unmount()
        })

        it('handles a large group with many events', () => {
            const nodes = Array.from({ length: 10 }, (_, i) => eventNode(`event-${i}`))
            const logic = mountLogic([groupNode(nodes)], 'split_large')

            logic.actions.splitGroup(0)

            expect(logic.values.series).toHaveLength(10)
            expect(logic.values.series.map((node: any) => node.event)).toEqual(
                Array.from({ length: 10 }, (_, i) => `event-${i}`)
            )
            logic.unmount()
        })

        it('leaves a non-group series alone', () => {
            const logic = mountLogic([eventNode('$pageview')], 'split_non_group')

            logic.actions.splitGroup(0)

            expect(logic.values.series).toEqual([eventNode('$pageview')])
            logic.unmount()
        })
    })

    describe('duplicating a group', () => {
        const group = (): GroupNode => groupNode([eventNode('$pageview'), eventNode('$exception')])

        it('duplicates a lone group into two identical groups', async () => {
            const logic = mountLogic([group()], 'duplicate_single_group')
            const original = logic.values.localSeries[0]

            await expectLogic(logic, () => {
                logic.actions.duplicateSeries(0)
            }).toDispatchActions(['duplicateSeries', 'setLocalSeries'])

            const local = logic.values.localSeries
            expect(local).toHaveLength(2)
            expect(local.map((l) => l.node.kind)).toEqual([NodeKind.GroupNode, NodeKind.GroupNode])
            expect(local[1].uuid).not.toBe(original.uuid)
            expect((local[1].node as GroupNode).nodes).toEqual((original.node as GroupNode).nodes)

            logic.unmount()
        })

        it('inserts the duplicate directly after the group and shifts trailing events', async () => {
            const logic = mountLogic([group(), eventNode('$pageleave')], 'duplicate_group_with_event')
            const original = logic.values.localSeries[0]

            await expectLogic(logic, () => {
                logic.actions.duplicateSeries(0)
            }).toDispatchActions(['duplicateSeries', 'setLocalSeries'])

            const local = logic.values.localSeries
            expect(local).toHaveLength(3)
            expect(local.map((l) => l.node.kind)).toEqual([NodeKind.GroupNode, NodeKind.GroupNode, NodeKind.EventsNode])
            expect(local[1].uuid).not.toBe(original.uuid)
            expect((local[1].node as GroupNode).nodes).toEqual((original.node as GroupNode).nodes)

            logic.unmount()
        })
    })

    describe('group custom_name handling', () => {
        it('preserves custom_name through rename via entityFilterLogic', async () => {
            const logic = mountLogic([groupNode([eventNode('$pageview')])], 'rename_group_test')

            logic.actions.selectSeries(0, logic.values.series[0], logic.values.localSeries[0].uuid)

            await expectLogic(logic, () => {
                logic.actions.renameSeries('Revenue events')
            }).toDispatchActions(['renameSeries', 'setLocalSeries'])

            expect(logic.values.series[0].custom_name).toBe('Revenue events')
            expect(logic.values.series[0].kind).toBe(NodeKind.GroupNode)

            logic.unmount()
        })
    })

    describe('legacyFiltersToSeries with groups', () => {
        it('includes group filters in the series', () => {
            const series = legacyFiltersToSeries({
                events: [{ id: '$pageview', type: EntityTypes.EVENTS, name: '$pageview', order: 0 }],
                groups: [
                    {
                        id: null,
                        type: EntityTypes.GROUPS,
                        name: 'group',
                        order: 1,
                        operator: FilterLogicalOperator.Or,
                        nestedFilters: [{ id: '$exception', type: EntityTypes.EVENTS, name: '$exception', order: 0 }],
                    },
                ],
            } as FilterType)

            expect(series).toHaveLength(2)
            expect(series[0]).toEqual(expect.objectContaining({ kind: NodeKind.EventsNode, event: '$pageview' }))
            expect(series[1]).toEqual(
                expect.objectContaining({
                    kind: NodeKind.GroupNode,
                    nodes: [expect.objectContaining({ kind: NodeKind.EventsNode, event: '$exception' })],
                })
            )
        })

        it('maintains order across mixed filters and groups', () => {
            const series = legacyFiltersToSeries({
                events: [
                    { id: '$pageview', type: EntityTypes.EVENTS, name: '$pageview', order: 0 },
                    { id: '$pageleave', type: EntityTypes.EVENTS, name: '$pageleave', order: 2 },
                ],
                groups: [
                    {
                        id: null,
                        type: EntityTypes.GROUPS,
                        name: 'group',
                        order: 1,
                        operator: FilterLogicalOperator.Or,
                        nestedFilters: [{ id: '$exception', type: EntityTypes.EVENTS, name: '$exception', order: 0 }],
                    },
                ],
            } as FilterType)

            expect(series.map((node) => node.kind)).toEqual([
                NodeKind.EventsNode,
                NodeKind.GroupNode,
                NodeKind.EventsNode,
            ])
        })
    })

    describe('nested row identity', () => {
        const mountGroupLogic = (
            nodes: AnyEntityNode[],
            typeKey: string
        ): ReturnType<typeof actionFilterGroupLogic.build> => {
            const parent = mountLogic([groupNode(nodes)], typeKey)
            const logic = actionFilterGroupLogic({
                filterUuid: parent.values.localSeries[0].uuid,
                typeKey,
                groupIndex: 0,
            })
            logic.mount()
            return logic
        }

        it('keeps each surviving nested row on its own uuid when one is removed', () => {
            const logic = mountGroupLogic(
                [eventNode('$pageview'), eventNode('$autocapture'), eventNode('$rageclick')],
                'nested_removal'
            )
            const originalUuids = logic.values.nestedRows.map(({ uuid }) => uuid)
            expect(originalUuids).toHaveLength(3)

            logic.actions.removeNestedSeries(0)

            // Keying by index would move each surviving row's open property panel onto the next event.
            expect(logic.values.nestedRows.map(({ uuid }) => uuid)).toEqual(originalUuids.slice(1))
        })

        it('keeps every nested row on its uuid when one of them switches event', () => {
            const logic = mountGroupLogic([eventNode('$pageview'), eventNode('$autocapture')], 'nested_update')
            const originalUuids = logic.values.nestedRows.map(({ uuid }) => uuid)

            logic.actions.updateNestedSeries(1, { event: '$rageclick', name: '$rageclick' } as Partial<AnyEntityNode>)

            expect(logic.values.nestedRows.map(({ uuid }) => uuid)).toEqual(originalUuids)
            expect(logic.values.nestedNodes[1]).toEqual(expect.objectContaining({ event: '$rageclick' }))
        })
    })
})
