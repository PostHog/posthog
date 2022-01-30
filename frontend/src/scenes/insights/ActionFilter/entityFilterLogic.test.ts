import { entityFilterLogic, toLocalFilters } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import filtersJson from './__mocks__/filters.json'
import eventDefinitionsJson from './__mocks__/event_definitions.json'
import { FilterType } from '~/types'
import { actionsModel } from '~/models/actionsModel'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'

jest.mock('lib/api')

describe('entityFilterLogic', () => {
    let logic: ReturnType<typeof entityFilterLogic.build>

    mockAPI(async ({ pathname }) => {
        if (pathname === `api/projects/${MOCK_TEAM_ID}/actions/`) {
            return {
                results: filtersJson.actions,
            }
        } else if (pathname.endsWith('/event_definitions/')) {
            return eventDefinitionsJson
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

            expect(logic.props.setFilters).toBeCalledWith(
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
