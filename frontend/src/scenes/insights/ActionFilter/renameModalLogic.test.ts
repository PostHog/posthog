import { BuiltLogic } from 'kea'
import {
    BareEntity,
    entityFilterLogic,
    EntityFilterProps,
    LocalFilter,
} from 'scenes/insights/ActionFilter/entityFilterLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import filtersJson from './__mocks__/filters.json'
import { EntityFilter } from '~/types'
import { renameModalLogicType } from 'scenes/insights/ActionFilter/renameModalLogicType'
import { renameModalLogic, RenameModalProps } from 'scenes/insights/ActionFilter/renameModalLogic'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { entityFilterLogicType } from 'scenes/insights/ActionFilter/entityFilterLogicType'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

jest.mock('lib/api')

describe('renameModalLogic', () => {
    let logic: BuiltLogic<renameModalLogicType<RenameModalProps>>
    let relevantEntityFilterLogic: BuiltLogic<entityFilterLogicType<BareEntity, EntityFilterProps, LocalFilter>>

    mockAPI(async (url) => {
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: entityFilterLogic,
        props: {
            setFilters: jest.fn(),
            filters: filtersJson,
            typeKey: 'logic_test',
        },
        onLogic: (l) => (relevantEntityFilterLogic = l),
    })
    initKeaTestLogic({
        logic: renameModalLogic,
        props: {
            filter: filtersJson.events[0] as EntityFilter,
            typeKey: 'logic_test',
        },
        onLogic: (l) => (logic = l),
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
