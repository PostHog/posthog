import { initKeaTests } from '~/test/init'
import { api, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { mockEventPropertyDefinitions } from '~/test/mocks'
import { useMocks } from '~/mocks/jest'
import { organizationLogic } from 'scenes/organizationLogic'
import { eventPropertyDefinitionsTableLogic } from 'scenes/data-management/event-properties/eventPropertyDefinitionsTableLogic'

describe('eventPropertyDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof eventPropertyDefinitionsTableLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/property_definitions': (req) => {
                    if (req.url.searchParams.get('limit') === '5' && !req.url.searchParams.get('offset')) {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(0, 5),
                                count: 5,
                                previous: null,
                                next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                            },
                        ]
                    }
                    if (req.url.searchParams.get('limit') === '5' && req.url.searchParams.get('offset') === '5') {
                        return [
                            200,
                            {
                                results: mockEventPropertyDefinitions.slice(5, 8),
                                count: 3,
                                previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`,
                                next: null,
                            },
                        ]
                    }
                },
            },
        })
        initKeaTests()
        organizationLogic.mount()
        await expectLogic(organizationLogic)
            .toFinishAllListeners()
            .toDispatchActions(['loadCurrentOrganizationSuccess'])
        jest.spyOn(api, 'get')
        api.get.mockClear()
        logic = eventPropertyDefinitionsTableLogic({
            key: '1',
            syncWithUrl: true,
        })
        logic.mount()
    })

    // describe('event definitions', () => {
    //     it('load event definitions on mount and cache', async () => {
    //         await expectLogic(logic)
    //             .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
    //             .toMatchValues({
    //                 eventDefinitions: partial({
    //                     count: 50,
    //                     results: mockEventDefinitions.slice(0, 50),
    //                     previous: null,
    //                     next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`,
    //                 }),
    //                 apiCache: partial({
    //                     [`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`]: partial({
    //                         count: 50,
    //                     }),
    //                 }),
    //             })
    //
    //         expect(api.get).toBeCalledTimes(1)
    //         expect(api.get).toBeCalledWith(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`)
    //
    //         await expectLogic(logic, () => {
    //             logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`)
    //         }).toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
    //
    //         // Doesn't call api.get again
    //         expect(api.get).toBeCalledTimes(1)
    //     })
    //
    //     it('pagination forwards and backwards', async () => {
    //         await expectLogic(logic)
    //             .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
    //             .toMatchValues({
    //                 eventDefinitions: partial({
    //                     count: 50,
    //                     next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`,
    //                 }),
    //             })
    //         expect(api.get).toBeCalledTimes(1)
    //         // Forwards
    //         await expectLogic(logic, () => {
    //             logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`)
    //         })
    //             .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
    //             .toFinishAllListeners()
    //             .toMatchValues({
    //                 eventDefinitions: partial({
    //                     count: 6,
    //                     previous: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`,
    //                     next: null,
    //                 }),
    //             })
    //         expect(api.get).toBeCalledTimes(2)
    //         // Backwards
    //         await expectLogic(logic, () => {
    //             logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`)
    //         })
    //             .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
    //             .toMatchValues({
    //                 eventDefinitions: partial({
    //                     count: 50,
    //                     next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50&offset=50`,
    //                 }),
    //             })
    //         expect(api.get).toBeCalledTimes(2)
    //     })
    // })
    //
    // // TODO: unbork this
    // describe.skip('property definitions', () => {
    //     const eventDefinition = mockEventDefinitions[0]
    //
    //     it('load property definitions and cache', async () => {
    //         await expectLogic(logic, () => {
    //             logic.actions.loadPropertiesForEvent(eventDefinition)
    //         })
    //             .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
    //             .toMatchValues({
    //                 eventPropertiesCacheMap: partial({
    //                     [eventDefinition.id]: partial({
    //                         count: 5,
    //                         results: mockEventPropertyDefinitions.slice(0, 5),
    //                         previous: null,
    //                         current: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`,
    //                         next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
    //                     }),
    //                 }),
    //                 apiCache: partial({
    //                     [`api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`]: partial({
    //                         count: 5,
    //                     }),
    //                     [`api/projects/${MOCK_TEAM_ID}/events?event=event1&limit=1`]: partial(mockEvent.properties),
    //                 }),
    //             })
    //
    //         expect(api.get).toBeCalledTimes(3)
    //         expect(api.get).toHaveBeenNthCalledWith(1, `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=50`)
    //         expect(api.get).toHaveBeenNthCalledWith(2, `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`)
    //         expect(api.get).toHaveBeenNthCalledWith(3, `api/projects/${MOCK_TEAM_ID}/events?event=event1&limit=1`)
    //
    //         await expectLogic(logic, () => {
    //             logic.actions.loadPropertiesForEvent(
    //                 eventDefinition,
    //                 `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`
    //             )
    //         }).toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
    //
    //         // Doesn't call api.get again
    //         expect(api.get).toBeCalledTimes(3)
    //     })
    //
    //     it('inject example', async () => {
    //         await expectLogic(logic, () => {
    //             logic.actions.loadPropertiesForEvent({ ...eventDefinition, name: 'event_with_example' })
    //         })
    //             .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
    //             .toMatchValues({
    //                 eventPropertiesCacheMap: partial({
    //                     [eventDefinition.id]: partial({
    //                         count: 5,
    //                         previous: null,
    //                         results: mockEventPropertyDefinitions.slice(0, 5).map((prop) =>
    //                             prop.name === '$browser'
    //                                 ? {
    //                                       ...prop,
    //                                       example: 'Chrome',
    //                                   }
    //                                 : prop
    //                         ),
    //                         next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
    //                     }),
    //                 }),
    //             })
    //     })
    //
    //     it('pagination forwards and backwards', async () => {
    //         await expectLogic(logic, () => {
    //             logic.actions.loadPropertiesForEvent(eventDefinition)
    //         })
    //             .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
    //             .toMatchValues({
    //                 eventPropertiesCacheMap: partial({
    //                     [eventDefinition.id]: partial({
    //                         count: 5,
    //                         next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
    //                     }),
    //                 }),
    //             })
    //         expect(api.get).toBeCalledTimes(3)
    //         // Forwards
    //         await expectLogic(logic, () => {
    //             logic.actions.loadPropertiesForEvent(
    //                 eventDefinition,
    //                 `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`
    //             )
    //         })
    //             .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
    //             .toMatchValues({
    //                 eventPropertiesCacheMap: partial({
    //                     [eventDefinition.id]: partial({
    //                         count: 3,
    //                         previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`,
    //                         next: null,
    //                     }),
    //                 }),
    //             })
    //         expect(api.get).toBeCalledTimes(4)
    //         // Backwards
    //         await expectLogic(logic, () => {
    //             logic.actions.loadPropertiesForEvent(
    //                 eventDefinition,
    //                 `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`
    //             )
    //         })
    //             .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
    //             .toMatchValues({
    //                 eventPropertiesCacheMap: partial({
    //                     [eventDefinition.id]: partial({
    //                         count: 5,
    //                         next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
    //                     }),
    //                 }),
    //             })
    //         expect(api.get).toBeCalledTimes(4)
    //     })
    // })
})
