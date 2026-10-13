import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import * as libUtils from 'lib/utils/dom'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FilterType, PropertyFilterType, PropertyOperator } from '~/types'

import eventDefinitionsJson from './__mocks__/event_definitions.json'
import filtersJson from './__mocks__/filters.json'
import { legacyFiltersToSeries } from './legacyFilters'
import { SeriesNode } from './seriesNode'

const baseSeries = (): SeriesNode[] => legacyFiltersToSeries(filtersJson as FilterType)

describe('entityFilterLogic', () => {
    let logic: ReturnType<typeof entityFilterLogic.build>

    beforeEach(() => {
        ;(libUtils as any).uuid = jest.fn().mockReturnValue('generated-uuid')
        useMocks({
            get: {
                '/api/projects/:team/actions/': {
                    results: filtersJson.actions,
                },
                '/api/projects/:team/event_definitions/': eventDefinitionsJson,
            },
        })
        initKeaTests()
        logic = entityFilterLogic({
            onChange: jest.fn(),
            series: baseSeries(),
            typeKey: 'logic_test',
        })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('series', async () => {
            await expectLogic(logic).toMatchValues({
                series: baseSeries(),
            })
        })
    })

    describe('renaming series', () => {
        it('renames successfully', async () => {
            await expectLogic(logic, () => {
                logic.actions.selectSeries(0, logic.values.series[0], logic.values.localSeries[0].uuid)
            })

            await expectLogic(logic, () => {
                logic.actions.renameSeries('Custom event name')
            }).toDispatchActions(['renameSeries', 'setLocalSeries'])

            expect(logic.props.onChange).toHaveBeenCalledWith(
                expect.arrayContaining([
                    expect.objectContaining({
                        custom_name: 'Custom event name',
                    }),
                ])
            )
        })

        it('applies the rename and closes the modal without yielding', () => {
            logic.actions.selectSeries(0, logic.values.series[0], logic.values.localSeries[0].uuid)
            logic.actions.showModal()

            logic.actions.renameSeries('Custom event name')

            expect(logic.values.series[0].custom_name).toEqual('Custom event name')
            expect(logic.values.modalVisible).toBe(false)
        })

        it('closes the modal when no series is selected', () => {
            logic.actions.showModal()

            logic.actions.renameSeries('Custom event name')

            expect(logic.values.modalVisible).toBe(false)
        })

        it('does not rename another series when the selected series is removed', () => {
            logic.actions.selectSeries(0, logic.values.series[0], logic.values.localSeries[0].uuid)
            logic.actions.showModal()
            logic.actions.setLocalSeries([{ uuid: 'replacement-uuid', node: logic.values.series[1] }])

            logic.actions.renameSeries('Custom event name')

            expect(logic.values.series[0].custom_name).not.toEqual('Custom event name')
            expect(logic.values.modalVisible).toBe(false)
        })
    })

    describe('modal behavior', () => {
        it('hides modal', () => {
            expectLogic(logic, () => {
                logic.actions.hideModal()
            })
                .toDispatchActions(['hideModal'])
                .toMatchValues({ modalVisible: false })
        })

        it('shows modal', () => {
            expectLogic(logic, () => {
                logic.actions.showModal()
            })
                .toDispatchActions(['showModal'])
                .toMatchValues({ modalVisible: true })
        })
    })

    describe('setSeries preserves UUIDs', () => {
        let uuidCounter: number

        beforeEach(() => {
            uuidCounter = 0
            ;(libUtils as any).uuid = jest.fn(() => `uuid-${uuidCounter++}`)

            logic.unmount()
            logic = entityFilterLogic({
                onChange: jest.fn(),
                series: baseSeries(),
                typeKey: 'uuid_test',
            })
            logic.mount()
        })

        it('preserves UUIDs when called with identical series', () => {
            const originalUuids = logic.values.localSeries.map((l) => l.uuid)

            logic.actions.setSeries(baseSeries())

            expect(logic.values.localSeries.map((l) => l.uuid)).toEqual(originalUuids)
        })

        it('preserves existing UUIDs when a series is added', () => {
            const originalUuids = logic.values.localSeries.map((l) => l.uuid)

            logic.actions.setSeries([
                ...baseSeries(),
                { kind: NodeKind.EventsNode, event: '$autocapture', name: '$autocapture' },
            ])

            const newSeries = logic.values.localSeries
            expect(newSeries).toHaveLength(4)
            expect(newSeries[0].uuid).toBe(originalUuids[0])
            expect(newSeries[1].uuid).toBe(originalUuids[1])
            expect(newSeries[2].uuid).toBe(originalUuids[2])
            expect(originalUuids).not.toContain(newSeries[3].uuid)
        })

        it('keeps each surviving row on its own uuid when a series is removed', () => {
            const originalUuids = logic.values.localSeries.map((l) => l.uuid)

            logic.actions.removeSeries(0)

            // Rebuilding the uuids by index would shift every row's identity up by one, which
            // moves open property panels and drag handles onto the wrong series.
            expect(logic.values.localSeries.map((l) => l.uuid)).toEqual(originalUuids.slice(1))
        })

        it('preserves UUIDs for remaining series when one is removed', () => {
            const originalUuids = logic.values.localSeries.map((l) => l.uuid)
            const remaining = baseSeries().filter((_, index) => index !== 0)

            logic.actions.setSeries(remaining)

            const newSeries = logic.values.localSeries
            expect(newSeries).toHaveLength(2)
            expect(originalUuids).toContain(newSeries[0].uuid)
            expect(originalUuids).toContain(newSeries[1].uuid)
        })
    })

    describe('updateSeriesMath preserves math_property_type', () => {
        it('keeps math_property_type when updating math', async () => {
            await expectLogic(logic, () => {
                logic.actions.updateSeriesMath(0, {
                    math: 'median',
                    math_property: '$session_duration',
                    math_property_type: TaxonomicFilterGroupType.SessionProperties,
                })
            }).toDispatchActions(['updateSeriesMath', 'setLocalSeries'])

            expect(logic.props.onChange).toHaveBeenCalledWith(
                expect.arrayContaining([
                    expect.objectContaining({
                        math: 'median',
                        math_property: '$session_duration',
                        math_property_type: TaxonomicFilterGroupType.SessionProperties,
                    }),
                ])
            )
        })

        it('clears math_property_type when math is cleared', async () => {
            logic.actions.updateSeriesMath(0, {
                math: 'median',
                math_property: '$session_duration',
                math_property_type: TaxonomicFilterGroupType.SessionProperties,
            })

            await expectLogic(logic, () => {
                logic.actions.updateSeriesMath(0, {
                    math: undefined,
                    math_property: undefined,
                    math_property_type: undefined,
                })
            }).toDispatchActions(['updateSeriesMath', 'setLocalSeries'])

            expect(logic.props.onChange).toHaveBeenLastCalledWith(
                expect.arrayContaining([
                    expect.objectContaining({
                        math_property_type: undefined,
                    }),
                ])
            )
        })
    })

    describe('updateSeriesEntity across node kinds', () => {
        const personProperty: AnyPropertyFilter = {
            key: 'email',
            value: 'test@posthog.com',
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Person,
        }
        const extendedPersonProperty: AnyPropertyFilter = {
            key: 'customers.plan',
            value: ['pro'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.DataWarehousePersonProperty,
        }
        const dwColumnProperty: AnyPropertyFilter = {
            key: 'status',
            value: ['complete'],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.DataWarehouse,
        }
        const hogqlProperty: AnyPropertyFilter = {
            key: 'amount > 0',
            type: PropertyFilterType.HogQL,
        }

        const eventNode = {
            kind: NodeKind.EventsNode,
            event: '$pageview',
            name: '$pageview',
            properties: [personProperty, extendedPersonProperty, dwColumnProperty, hogqlProperty],
        } as SeriesNode
        const dataWarehouseNode = {
            kind: NodeKind.DataWarehouseNode,
            id: 'payments',
            name: 'payments',
            table_name: 'payments',
            properties: [dwColumnProperty, hogqlProperty],
        } as SeriesNode
        const switchToPayments = {
            kind: NodeKind.DataWarehouseNode,
            key: 'payments',
            name: 'payments',
        }

        it.each([
            [
                'drops person-scoped filters when an event becomes a data warehouse series',
                eventNode,
                switchToPayments,
                [hogqlProperty],
            ],
            [
                'drops column filters when a data warehouse series becomes an event',
                dataWarehouseNode,
                { kind: NodeKind.EventsNode, key: '$pageview', name: '$pageview' },
                [hogqlProperty],
            ],
            [
                'drops column filters when the data warehouse table changes',
                dataWarehouseNode,
                { kind: NodeKind.DataWarehouseNode, key: 'orders', name: 'orders' },
                [hogqlProperty],
            ],
            [
                'keeps column filters when the data warehouse table is unchanged',
                dataWarehouseNode,
                { ...switchToPayments, timestamp_field: 'created_at' },
                [dwColumnProperty, hogqlProperty],
            ],
        ] as [string, SeriesNode, Record<string, any>, AnyPropertyFilter[]][])(
            '%s',
            async (_name, initialNode, update, expectedProperties) => {
                logic.actions.setLocalSeries([{ uuid: 'uuid-0', node: initialNode }])

                await expectLogic(logic, () => {
                    logic.actions.updateSeriesEntity(0, update as any)
                }).toDispatchActions(['updateSeriesEntity', 'setLocalSeries'])

                expect(logic.values.series[0].properties).toEqual(expectedProperties)
            }
        )

        const eventPropertyMath = {
            ...eventNode,
            math: 'sum',
            math_property: 'revenue',
            math_property_type: TaxonomicFilterGroupType.NumericalEventProperties,
        } as SeriesNode
        const dataWarehousePropertyMath = {
            ...dataWarehouseNode,
            math: 'sum',
            math_property: 'amount',
            math_property_type: TaxonomicFilterGroupType.DataWarehouseProperties,
        } as SeriesNode

        it.each([
            [
                'drops property math when an event becomes a data warehouse series',
                eventPropertyMath,
                switchToPayments,
                { math: undefined, math_property: undefined, math_property_type: undefined },
            ],
            [
                'drops property math when a data warehouse series becomes an event',
                dataWarehousePropertyMath,
                { kind: NodeKind.EventsNode, key: '$pageview', name: '$pageview' },
                { math: undefined, math_property: undefined, math_property_type: undefined },
            ],
            [
                'drops property math when the data warehouse table changes',
                dataWarehousePropertyMath,
                { kind: NodeKind.DataWarehouseNode, key: 'orders', name: 'orders' },
                { math: undefined, math_property: undefined, math_property_type: undefined },
            ],
            [
                'keeps property math when the data warehouse table is unchanged',
                dataWarehousePropertyMath,
                { ...switchToPayments, timestamp_field: 'created_at' },
                {
                    math: 'sum',
                    math_property: 'amount',
                    math_property_type: TaxonomicFilterGroupType.DataWarehouseProperties,
                },
            ],
            [
                'keeps math that does not depend on a property',
                { ...eventNode, math: 'dau' } as SeriesNode,
                switchToPayments,
                { math: 'dau', math_property: undefined, math_property_type: undefined },
            ],
        ] as [string, SeriesNode, Record<string, any>, Record<string, any>][])(
            '%s',
            async (_name, initialNode, update, expectedMath) => {
                logic.actions.setLocalSeries([{ uuid: 'uuid-0', node: initialNode }])

                await expectLogic(logic, () => {
                    logic.actions.updateSeriesEntity(0, update as any)
                }).toDispatchActions(['updateSeriesEntity', 'setLocalSeries'])

                expect(logic.values.series[0]).toMatchObject(expectedMath)
            }
        )

        it('coerces a string action id to the integer the schema types', async () => {
            logic.actions.setLocalSeries([{ uuid: 'uuid-0', node: eventNode }])

            await expectLogic(logic, () => {
                logic.actions.updateSeriesEntity(0, {
                    kind: NodeKind.ActionsNode,
                    key: '9',
                    name: 'Users signed up',
                })
            }).toDispatchActions(['updateSeriesEntity'])

            expect(logic.values.series[0]).toMatchObject({ kind: NodeKind.ActionsNode, id: 9 })
        })
    })

    describe('duplicating series', () => {
        it('preserves custom_name when duplicating', async () => {
            logic.actions.setLocalSeries([
                {
                    uuid: 'uuid-0',
                    node: {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                        name: '$pageview',
                        custom_name: 'My custom label',
                    },
                },
            ])

            await expectLogic(logic, () => {
                logic.actions.duplicateSeries(0)
            }).toDispatchActions(['duplicateSeries', 'setLocalSeries'])

            expect(logic.props.onChange).toHaveBeenLastCalledWith([
                expect.objectContaining({ event: '$pageview', custom_name: 'My custom label' }),
                expect.objectContaining({ event: '$pageview', custom_name: 'My custom label' }),
            ])
        })
    })
})
