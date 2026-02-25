import { expectLogic } from 'kea-test-utils'

import * as libUtils from 'lib/utils'
import { entityFilterLogic, toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterType } from '~/types'

import eventDefinitionsJson from './__mocks__/event_definitions.json'
import filtersJson from './__mocks__/filters.json'

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
            setFilters: jest.fn(),
            filters: filtersJson,
            typeKey: 'logic_test',
        })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('localFilters', async () => {
            await expectLogic(logic).toMatchValues({
                localFilters: toLocalFilters(filtersJson as FilterType),
            })
        })
    })

    describe('renaming filters', () => {
        it('renames successfully', async () => {
            // Select a filter to rename first
            await expectLogic(logic, () => {
                logic.actions.selectFilter({
                    id: '$pageview',
                    name: '$pageview',
                    order: 0,
                })
            })

            await expectLogic(logic, () => {
                logic.actions.renameFilter('Custom event name')
            }).toDispatchActions(['renameFilter', 'updateFilter', 'setFilters'])

            expect(logic.props.setFilters).toHaveBeenCalledWith(
                expect.objectContaining({
                    events: expect.arrayContaining([
                        expect.objectContaining({
                            custom_name: 'Custom event name',
                        }),
                    ]),
                })
            )
        })

        it('closes modal after renaming', () => {
            expectLogic(logic, () => {
                logic.actions.renameFilter('Custom event name')
            })
                .toDispatchActions(['renameFilter', 'hideModal'])
                .toMatchValues({ modalVisible: false })
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

    describe('setLocalFilters preserves UUIDs', () => {
        let uuidCounter: number

        beforeEach(() => {
            uuidCounter = 0
            ;(libUtils as any).uuid = jest.fn(() => `uuid-${uuidCounter++}`)

            logic.unmount()
            logic = entityFilterLogic({
                setFilters: jest.fn(),
                filters: filtersJson,
                typeKey: 'uuid_test',
            })
            logic.mount()
        })

        it('preserves UUIDs when called with identical filters', () => {
            const originalUuids = logic.values.localFilters.map((f) => f.uuid)

            logic.actions.setLocalFilters(filtersJson as FilterType)

            expect(logic.values.localFilters.map((f) => f.uuid)).toEqual(originalUuids)
        })

        it('preserves existing UUIDs when a filter is added', () => {
            const originalUuids = logic.values.localFilters.map((f) => f.uuid)

            logic.actions.setLocalFilters({
                ...filtersJson,
                events: [...filtersJson.events, { id: '$autocapture', name: '$autocapture', type: 'events', order: 3 }],
            } as FilterType)

            const newFilters = logic.values.localFilters
            expect(newFilters).toHaveLength(4)
            expect(newFilters[0].uuid).toBe(originalUuids[0])
            expect(newFilters[1].uuid).toBe(originalUuids[1])
            expect(newFilters[2].uuid).toBe(originalUuids[2])
            expect(originalUuids).not.toContain(newFilters[3].uuid)
        })

        it('preserves UUIDs for remaining filters when one is removed', () => {
            const originalUuids = logic.values.localFilters.map((f) => f.uuid)

            logic.actions.setLocalFilters({
                ...filtersJson,
                events: [filtersJson.events[1]],
            } as FilterType)

            const newFilters = logic.values.localFilters
            expect(newFilters).toHaveLength(2)
            expect(originalUuids).toContain(newFilters[0].uuid)
            expect(originalUuids).toContain(newFilters[1].uuid)
        })
    })

    describe('duplicating filters', () => {
        it('preserves custom_name when duplicating', async () => {
            await expectLogic(logic, () => {
                logic.actions.duplicateFilter({
                    id: '$pageview',
                    name: '$pageview',
                    custom_name: 'My custom label',
                    order: 0,
                    type: 'events',
                })
            }).toDispatchActions(['duplicateFilter', 'setFilters'])

            expect(logic.props.setFilters).toHaveBeenCalledWith(
                expect.objectContaining({
                    events: expect.arrayContaining([
                        expect.objectContaining({
                            id: '$pageview',
                            custom_name: 'My custom label',
                            order: 1,
                        }),
                    ]),
                })
            )
        })
    })
})
