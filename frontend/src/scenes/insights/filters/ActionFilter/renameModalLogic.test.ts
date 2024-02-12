import { expectLogic } from 'kea-test-utils'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { renameModalLogic } from 'scenes/insights/filters/ActionFilter/renameModalLogic'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

import { initKeaTests } from '~/test/init'
import { EntityFilter } from '~/types'

import filtersJson from './__mocks__/filters.json'

describe('renameModalLogic', () => {
    let logic: ReturnType<typeof renameModalLogic.build>
    let relevantEntityFilterLogic: ReturnType<typeof entityFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
        relevantEntityFilterLogic = entityFilterLogic({
            setFilters: jest.fn(),
            filters: filtersJson,
            typeKey: 'logic_test',
        })
        relevantEntityFilterLogic.mount()
        logic = renameModalLogic({
            filter: filtersJson.events[0] as EntityFilter,
            typeKey: 'logic_test',
        })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([relevantEntityFilterLogic])
        })

        it('name', async () => {
            await expectLogic(logic).toMatchValues({
                name: getDisplayNameFromEntityFilter(filtersJson.events[0] as EntityFilter),
            })
        })
    })

    describe('modifying name', () => {
        it('set name', () => {
            expectLogic(logic, () => {
                logic.actions.setName('veggie_straws')
            })
                .toDispatchActions(['setName'])
                .toMatchValues({ name: 'veggie_straws' })
        })

        it('set filter', async () => {
            await expectLogic(relevantEntityFilterLogic, () => {
                relevantEntityFilterLogic.actions.selectFilter({
                    ...filtersJson.events[0],
                    custom_name: 'zesty_veggie_straws',
                } as EntityFilter)
            }).toDispatchActions(['selectFilter'])

            await expectLogic(logic).toMatchValues({
                name: 'zesty_veggie_straws',
            })
        })
    })
})
