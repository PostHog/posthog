import { initKeaTests } from '~/test/init'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { api, MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { mockEvent, mockEventDefinitions, mockEventPropertyDefinitions } from '~/test/mocks'
import { toParams } from 'lib/utils'

jest.mock('lib/api')

describe('eventDefinitionsTableLogic', () => {
    let logic: ReturnType<typeof eventDefinitionsTableLogic.build>

    mockAPI(
        (url) => {
            if (
                url.pathname === `api/projects/${MOCK_TEAM_ID}/event_definitions` &&
                url.searchParams.limit === 30 &&
                !url.searchParams.offset
            ) {
                return {
                    results: mockEventDefinitions.slice(0, 30),
                    count: 30,
                    previous: null,
                    next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30&offset=30`,
                }
            }
            if (
                url.pathname === `api/projects/${MOCK_TEAM_ID}/event_definitions` &&
                url.searchParams.limit === 30 &&
                url.searchParams.offset === 30
            ) {
                return {
                    results: mockEventDefinitions.slice(30, 56),
                    count: 26,
                    previous: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`,
                    next: null,
                }
            }
            if (
                url.pathname === `api/projects/${MOCK_TEAM_ID}/property_definitions` &&
                url.searchParams.limit === 5 &&
                !url.searchParams.offset
            ) {
                return {
                    results: mockEventPropertyDefinitions.slice(0, 5),
                    count: 5,
                    previous: null,
                    next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                }
            }
            if (
                url.pathname === `api/projects/${MOCK_TEAM_ID}/property_definitions` &&
                url.searchParams.limit === 5 &&
                url.searchParams.offset === 5
            ) {
                return {
                    results: mockEventPropertyDefinitions.slice(5, 8),
                    count: 3,
                    previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`,
                    next: null,
                }
            }
            if (
                url.pathname === `api/projects/${MOCK_TEAM_ID}/events` &&
                url.searchParams.limit === 1 &&
                url.searchParams.event === 'event_with_example'
            ) {
                return {
                    results: [{ ...mockEvent, properties: { ...mockEvent.properties, $browser: 'Chrome' } }],
                    next: null,
                }
            }
            if (url.pathname === `api/projects/${MOCK_TEAM_ID}/events` && url.searchParams.limit === 1) {
                return { results: [mockEvent], next: null }
            }
        },
        (path, args) => {
            // Omit search params for property definitions and events for simplicity
            if (path === 'eventDefinitions.determineListEndpoint') {
                return `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`
            }
            if (path === 'propertyDefinitions.determineListEndpoint') {
                return `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`
            }
            if (path === 'events.determineListEndpoint') {
                return `api/projects/${MOCK_TEAM_ID}/events?${toParams({ ...args[0], limit: args[1] })}`
            }
        }
    )

    beforeEach(() => {
        initKeaTests()
        const logicProps = {
            key: '1',
            syncWithUrl: true,
        }
        logic = eventDefinitionsTableLogic(logicProps)
        logic.mount()
    })

    describe('event definitions', () => {
        it('load event definitions on mount and cache', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 30,
                        results: mockEventDefinitions.slice(0, 30),
                        previous: null,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30&offset=30`,
                    }),
                    apiCache: partial({
                        [`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`]: partial({
                            count: 30,
                        }),
                    }),
                })

            expect(api.get).toBeCalledTimes(1)
            expect(api.get).toBeCalledWith(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`)

            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`)
            }).toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])

            // Doesn't call api.get again
            expect(api.get).toBeCalledTimes(1)
        })

        it('pagination forwards and backwards', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 30,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30&offset=30`,
                    }),
                })
            expect(api.get).toBeCalledTimes(1)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30&offset=30`)
            })
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toFinishAllListeners()
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 26,
                        previous: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`,
                        next: null,
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadEventDefinitions(`api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`)
            })
                .toDispatchActions(['loadEventDefinitions', 'loadEventDefinitionsSuccess'])
                .toMatchValues({
                    eventDefinitions: partial({
                        count: 30,
                        next: `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30&offset=30`,
                    }),
                })
            expect(api.get).toBeCalledTimes(2)
        })
    })

    describe('property definitions', () => {
        const eventDefinition = mockEventDefinitions[0]

        it('load property definitions and cache', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition)
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            previous: null,
                            results: mockEventPropertyDefinitions.slice(0, 5),
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                    apiCache: partial({
                        [`api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`]: partial({
                            count: 5,
                        }),
                        [`api/projects/${MOCK_TEAM_ID}/events?limit=1`]: partial(mockEvent.properties),
                    }),
                })

            expect(api.get).toBeCalledTimes(3)
            expect(api.get).toHaveBeenNthCalledWith(1, `api/projects/${MOCK_TEAM_ID}/event_definitions?limit=30`)
            expect(api.get).toHaveBeenNthCalledWith(2, `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`)
            expect(api.get).toHaveBeenNthCalledWith(3, `api/projects/${MOCK_TEAM_ID}/events?limit=1`)

            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(
                    eventDefinition,
                    `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`
                )
            }).toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])

            // Doesn't call api.get again
            expect(api.get).toBeCalledTimes(3)
        })

        it('inject example', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent({ ...eventDefinition, name: 'event_with_example' })
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            previous: null,
                            results: mockEventPropertyDefinitions.slice(0, 5).map((prop) =>
                                prop.name === '$browser'
                                    ? {
                                          ...prop,
                                          example: 'Chrome',
                                      }
                                    : prop
                            ),
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                })
        })

        it('pagination forwards and backwards', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(eventDefinition)
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                })
            expect(api.get).toBeCalledTimes(3)
            // Forwards
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(
                    eventDefinition,
                    `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`
                )
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 3,
                            previous: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`,
                            next: null,
                        }),
                    }),
                })
            expect(api.get).toBeCalledTimes(4)
            // Backwards
            await expectLogic(logic, () => {
                logic.actions.loadPropertiesForEvent(
                    eventDefinition,
                    `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5`
                )
            })
                .toDispatchActions(['loadPropertiesForEvent', 'loadPropertiesForEventSuccess'])
                .toMatchValues({
                    eventPropertiesCacheMap: partial({
                        [eventDefinition.id]: partial({
                            count: 5,
                            next: `api/projects/${MOCK_TEAM_ID}/property_definitions?limit=5&offset=5`,
                        }),
                    }),
                })
            expect(api.get).toBeCalledTimes(4)
        })
    })
})
