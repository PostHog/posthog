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
})
