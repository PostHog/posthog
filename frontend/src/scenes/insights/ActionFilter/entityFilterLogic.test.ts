import { BuiltLogic } from 'kea'
import { entityFilterLogicType } from 'scenes/insights/ActionFilter/entityFilterLogicType'
import {
    BareEntity,
    entityFilterLogic,
    EntityFilterProps,
    LocalFilter,
    toLocalFilters,
} from 'scenes/insights/ActionFilter/entityFilterLogic'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import filtersJson from './__mocks__/filters.json'
import eventDefinitionsJson from './__mocks__/event_definitions.json'
import { FilterType } from '~/types'
import { actionsModel } from '~/models/actionsModel'
import { mockAPI } from 'lib/api.mock'

jest.mock('lib/api')

describe('entityFilterLogic', () => {
    let logic: BuiltLogic<entityFilterLogicType<BareEntity, EntityFilterProps, LocalFilter>>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/action/') {
            return {
                results: filtersJson.actions,
            }
        } else if (pathname === 'api/projects/@current/event_definitions/') {
            return eventDefinitionsJson
        } else if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

    initKeaTestLogic({
        logic: entityFilterLogic,
        props: {
            setFilters: jest.fn(),
            filters: filtersJson,
            typeKey: 'logic_test',
        },
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([actionsModel])
        })

        it('localFilters', async () => {
            await expectLogic(logic).toMatchValues({
                localFilters: toLocalFilters(filtersJson as FilterType),
            })
        })
    })

    describe('renaming filters', () => {
        const filterWithCustomName = {
            id: '$pageview',
            name: '$pageview',
            custom_name: 'Custom event name',
            order: 0,
        }

        it('renames successfully', async () => {
            await expectLogic(logic, () => {
                logic.actions.renameFilter(filterWithCustomName)
            }).toDispatchActions(['renameFilter', 'updateFilter', 'setFilters'])

            expect(logic.props.setFilters).toBeCalledWith(
                expect.objectContaining({
                    events: expect.arrayContaining([
                        expect.objectContaining({
                            custom_name: filterWithCustomName.custom_name,
                        }),
                    ]),
                })
            )
        })

        it('close modal after renaming', () => {
            expectLogic(logic, () => {
                logic.actions.renameFilter(filterWithCustomName)
            })
                .toDispatchActions(['renameFilter', 'setModalVisible'])
                .toMatchValues({ modalVisible: false })
        })
    })
})
