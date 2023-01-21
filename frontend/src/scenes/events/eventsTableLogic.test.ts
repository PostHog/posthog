import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { router } from 'kea-router'
import { lemonToast } from 'lib/components/lemonToast'
import { EmptyPropertyFilter, EventType, PropertyFilter, PropertyOperator } from '~/types'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import { fromParamsGivenUrl } from 'lib/utils'
import { useMocks } from '~/mocks/jest'

const errorToastSpy = jest.spyOn(lemonToast, 'error')

const timeNow = '2021-05-05T00:00:00.000Z'

jest.mock('lib/dayjs', () => {
    const dayjs = jest.requireActual('lib/dayjs')
    return { ...dayjs, now: () => dayjs.dayjs(timeNow) }
})

import { triggerExport } from 'lib/components/ExportButton/exporter'
import { MOCK_TEAM_ID } from 'lib/api.mock'
jest.mock('lib/components/ExportButton/exporter')

const randomBool = (): boolean => Math.random() < 0.5

const randomString = (): string => Math.random().toString(36).substring(2, 5)

const makeEvent = (id: string = '1', timestamp: string = randomString()): EventType => ({
    id: id,
    timestamp,
    elements: [],
    elements_hash: '',
    event: '',
    properties: {},
})

const makePropertyFilter = (value: string = randomString()): PropertyFilter => ({
    key: value,
    operator: PropertyOperator.Exact,
    type: 't',
    value: 'v',
})

const firstEvent = makeEvent('1', 'the first timestamp')
const secondEvent = makeEvent('1', '2023-05-05T00:00:00.000Z')

const beforeLastEventsTimestamp = '2023-05-05T00:00:00.000Z'
const afterTheFirstEvent = 'the first timestamp'
const afterOneYearAgo = '2020-05-05T00:00:00.000Z'
const fiveDaysAgo = '2021-04-30T00:00:00.000Z'
const orderByTimestamp = '["-timestamp"]'
const emptyProperties = '[]'

const getUrlParameters = (url: string): Record<string, any> => {
    return fromParamsGivenUrl('?' + (url.split('?').pop() || ''))
}

describe('eventsTableLogic', () => {
    let logic: ReturnType<typeof eventsTableLogic.build>

    beforeEach(() => {
        jest.spyOn(api, 'get')
        useMocks({
            get: {
                '/api/projects/:team/events/': { results: [], count: 0 },
            },
        })
        initKeaTests()
    })

    describe('when loaded on events page', () => {
        beforeEach(() => {
            router.actions.push(urls.events())
            logic = eventsTableLogic({
                key: 'test-key',
                sceneUrl: urls.events(),
            })
            logic.mount()
        })

        it('sets a key', () => {
            expect(logic.key).toEqual('all-test-key-/events')
        })

        it('starts with known defaults', async () => {
            await expectLogic(logic).toMatchValues({
                properties: expect.arrayContaining([]),
                eventFilter: '',
                isLoading: true,
                isLoadingNext: false,
                events: [],
                hasNext: false,
                orderBy: '-timestamp',
                selectedEvent: null,
                newEvents: [],
                highlightEvents: {},
                automaticLoadEnabled: false,
            })
        })

        describe('reducers', () => {
            it('can toggle autoloading on', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleAutomaticLoad(true)
                })
                    .toMatchValues({
                        automaticLoadEnabled: true,
                    })
                    .toDispatchActions(['fetchEvents', 'toggleAutomaticLoad'])
                    .toNotHaveDispatchedActions(['fetchEvents'])
            })

            it('can toggle autoloading on and off', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleAutomaticLoad(true)
                    logic.actions.toggleAutomaticLoad(false)
                })
                    .toMatchValues({
                        automaticLoadEnabled: false,
                    })
                    .toDispatchActions(['fetchEvents', 'toggleAutomaticLoad'])
                    .toNotHaveDispatchedActions(['fetchEvents'])
            })

            it('does not call prependNewEvents when there are zero new events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleAutomaticLoad(true)
                }).toMatchValues({
                    automaticLoadEnabled: true,
                })
            })

            it('does call prependNewEvents when there are new events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.pollEventsSuccess([makeEvent(), makeEvent(), makeEvent()])
                    logic.actions.toggleAutomaticLoad(true)
                })
                    .toMatchValues({
                        automaticLoadEnabled: true,
                    })
                    .toDispatchActions(['prependNewEvents'])
            })

            it('does not call prependNewEvents when there are new events but loading is off', async () => {
                await expectLogic(logic, () => {
                    logic.actions.pollEventsSuccess([makeEvent(), makeEvent(), makeEvent()])
                    logic.actions.toggleAutomaticLoad(false)
                }).toMatchValues({
                    automaticLoadEnabled: false,
                })
            })

            it('can set a poll timeout ID', async () => {
                const timeoutHandle = setTimeout(() => {})
                await expectLogic(logic, () => {
                    logic.actions.setPollTimeout(timeoutHandle)
                }).toMatchValues({
                    pollTimeout: timeoutHandle,
                })
            })

            it('can highlight new events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.prependEvents([makeEvent('potato')])
                }).toMatchValues({
                    highlightEvents: { potato: true },
                })
            })

            it('sets new events when polling succeeds', async () => {
                const apiResponse = [makeEvent('potato')]
                await expectLogic(logic, () => {
                    logic.actions.pollEventsSuccess(apiResponse)
                }).toMatchValues({
                    newEvents: apiResponse,
                })
            })

            it('clears new events when setting properties', async () => {
                const apiResponse = [makeEvent('potato')]
                await expectLogic(logic, () => {
                    logic.actions.pollEventsSuccess(apiResponse)
                    logic.actions.setProperties([])
                }).toMatchValues({
                    newEvents: [],
                })
            })

            it('clears new events when prepending new events', async () => {
                const apiResponse = [makeEvent('potato')]
                await expectLogic(logic, () => {
                    logic.actions.pollEventsSuccess(apiResponse)
                    logic.actions.prependEvents([])
                }).toMatchValues({
                    newEvents: [],
                })
            })

            // TODO but nothing uses this action
            it('can select an event', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setSelectedEvent(makeEvent('4'))
                }).toMatchValues({
                    selectedEvent: expect.objectContaining({ id: '4' }),
                })
            })

            it('fetch events success can set hasNext (which is the URL of the next page of results, that we do not use)', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: [], hasNext: true, isNext: false })
                }).toMatchValues({
                    hasNext: true,
                })
            })

            /**
             * It is relatively high coupling between implementation and test to assert directly on the API
             * But, the interaction between the state of the logic and the choices of API parameters that these mock
             * expectations should protect against accidental regression
             */
            describe('API calls are limited to a time window by the after param to improve ClickHouse performance', () => {
                it('fetch events sets after to 5 days ago when there are no events', async () => {
                    useMocks({
                        get: {
                            '/api/projects/:team/events/': {
                                results: [firstEvent, secondEvent],
                                hasNext: false,
                                isNext: false,
                            },
                        },
                    })
                    await expectLogic(logic, () => {
                        logic.actions.fetchEvents()
                    }).toDispatchActions(['fetchEventsSuccess'])

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                    })
                })

                it('fetch events sets after to 5 days ago and then a year ago when there are no events', async () => {
                    ;(api.get as jest.Mock).mockClear() // because it will have been called on mount

                    await expectLogic(logic, () => {
                        logic.actions.fetchEvents()
                    }).toFinishListeners()

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const firstGetCallUrl = mockCalls[0][0]
                    expect(getUrlParameters(firstGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                    })

                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: afterOneYearAgo,
                    })
                })

                it('fetch events doesnt set after to a year ago when five days ago returns some events', async () => {
                    useMocks({
                        get: {
                            '/api/projects/:team/events/': {
                                results: [firstEvent, secondEvent],
                                hasNext: false,
                                isNext: false,
                            },
                        },
                    })

                    await expectLogic(logic, () => {
                        logic.actions.fetchEvents()
                    }).toFinishListeners()

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                    })
                })

                it('fetch events sets after to five days ago when there are already events', async () => {
                    useMocks({
                        get: {
                            '/api/projects/:team/events/': {
                                results: [firstEvent, secondEvent],
                                hasNext: false,
                                isNext: false,
                            },
                        },
                    })
                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                        logic.actions.fetchEvents()
                    }).toDispatchActions(['fetchEventsSuccess', 'fetchEventsSuccess'])

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                    })
                })

                it('triggers fetch events on set properties', async () => {
                    useMocks({
                        get: {
                            '/api/projects/:team/events/': {
                                results: [firstEvent, secondEvent],
                                hasNext: false,
                                isNext: false,
                            },
                        },
                    })

                    await expectLogic(logic, () => {
                        logic.actions.setProperties([])
                    }).toDispatchActions(['fetchEventsSuccess'])

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                    })
                })

                it('triggers fetch events on set event filter', async () => {
                    useMocks({
                        get: {
                            '/api/projects/:team/events/': {
                                results: [firstEvent, secondEvent],
                                hasNext: false,
                                isNext: false,
                            },
                        },
                    })

                    const eventName = randomString()
                    await expectLogic(logic, () => {
                        logic.actions.setEventFilter(eventName)
                    }).toDispatchActions(['fetchEventsSuccess'])

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                        event: eventName,
                    })
                })

                it('adds now as the after parameter when there are no event results', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.pollEvents()
                    })

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: timeNow,
                    })
                })

                it('adds the timestamp of the most recent event as the after parameter when there are results', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                    }).toMatchValues({ events: [firstEvent, secondEvent] })

                    logic.actions.pollEvents()

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: afterTheFirstEvent,
                    })
                })

                it('triggers fetch events with before timestamp on fetchNextEvents when there are existing events', async () => {
                    useMocks({
                        get: {
                            '/api/projects/:team/events/': {
                                results: [firstEvent, secondEvent],
                                hasNext: false,
                                isNext: false,
                            },
                        },
                    })

                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                        logic.actions.fetchNextEvents()
                    }).toDispatchActions([
                        logic.actionCreators.fetchEvents({
                            before: secondEvent.timestamp,
                        }),
                        'fetchEventsSuccess',
                    ])

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        before: beforeLastEventsTimestamp,
                        after: fiveDaysAgo, // this is the default whenever events exist
                        // will revisit if `load more events` becomes problematic
                    })
                })

                it('preserves fetchNextEvents params when no new events found in the following timeslice', async () => {
                    ;(api.get as jest.Mock).mockClear() // because it will have been called on mount

                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                        logic.actions.fetchNextEvents()
                    })
                        .toDispatchActions([
                            logic.actionCreators.fetchEvents({
                                before: secondEvent.timestamp,
                            }),
                            'fetchEventsSuccess',
                        ])
                        .toFinishListeners()

                    const mockCalls = (api.get as jest.Mock).mock.calls
                    const firstGetCallUrl = mockCalls[0][0]
                    expect(getUrlParameters(firstGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: fiveDaysAgo,
                        before: beforeLastEventsTimestamp,
                    })

                    const lastGetCallUrl = mockCalls[mockCalls.length - 1][0]
                    expect(getUrlParameters(lastGetCallUrl)).toEqual({
                        properties: emptyProperties,
                        orderBy: orderByTimestamp,
                        after: afterOneYearAgo,
                        before: beforeLastEventsTimestamp,
                    })
                })
            })

            it('fetch events clears the has next flag', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: [], hasNext: true, isNext: false })
                    logic.actions.fetchEvents()
                }).toMatchValues({
                    hasNext: false,
                })
            })

            it('fetch next events clears the has next flag', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: [], hasNext: true, isNext: false })
                    logic.actions.fetchNextEvents()
                }).toMatchValues({
                    hasNext: false,
                })
            })

            it('sets events when preprendNewEvents is called', async () => {
                const events = [makeEvent('potato'), makeEvent('tomato')]
                await expectLogic(logic, () => {
                    logic.actions.prependEvents(events)
                }).toMatchValues({
                    events,
                })
            })

            it('replaces events when not loading a new "page"', async () => {
                const originalEvents = [makeEvent('potato'), makeEvent('tomato')]
                const subsequentEvents = [makeEvent('apple'), makeEvent('melon')]
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: originalEvents, hasNext: false, isNext: false })
                    logic.actions.fetchEventsSuccess({ events: subsequentEvents, hasNext: false, isNext: false })
                }).toMatchValues({
                    events: subsequentEvents,
                })
            })

            it('adds events when loading a new "page"', async () => {
                const originalEvents = [makeEvent('potato'), makeEvent('tomato')]
                const subsequentEvents = [makeEvent('apple'), makeEvent('melon')]
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: originalEvents, hasNext: false, isNext: false })
                    logic.actions.fetchEventsSuccess({ events: subsequentEvents, hasNext: false, isNext: true })
                }).toMatchValues({
                    events: [...originalEvents, ...subsequentEvents],
                })
            })

            it('can unset the isLoadingNext flag when succeeding', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchNextEvents()
                    logic.actions.fetchEventsSuccess({ events: [], hasNext: false, isNext: false })
                }).toMatchValues({
                    isLoadingNext: false,
                })
            })

            it('can set the isLoadingNext flag', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchNextEvents()
                }).toMatchValues({
                    isLoadingNext: true,
                })
            })

            describe('the isloading flag', () => {
                it('isloading starts true', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({ events: [], hasNext: randomBool(), isNext: randomBool() })
                    }).toMatchValues({ isLoading: false })
                })

                it('fetch events success set isloading to false', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({ events: [], hasNext: randomBool(), isNext: randomBool() })
                    }).toMatchValues({ isLoading: false })
                })

                it('fetch events failure set isloading to false', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.fetchOrPollFailure({})
                    }).toMatchValues({ isLoading: false })
                })

                it('Fetch Events sets isLoading to true', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.fetchEventsSuccess({ events: [], hasNext: randomBool(), isNext: randomBool() })
                        logic.actions.fetchEvents()
                    }).toMatchValues({ isLoading: true })
                })
            })

            describe('the event filter', () => {
                it('can set the event filter', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setEventFilter('event name')
                    }).toMatchValues({ eventFilter: 'event name' })
                })
            })

            describe('the properties', () => {
                it('can set the properties when empty', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.setProperties([])
                    }).toMatchValues({ properties: [] })

                    await expectLogic(logic, () => {
                        logic.actions.setProperties([{} as any])
                    }).toMatchValues({ properties: [] })
                })

                it('can set an object inside the array', async () => {
                    const propertyFilter = makePropertyFilter()
                    await expectLogic(logic, () => {
                        logic.actions.setProperties([propertyFilter])
                    }).toMatchValues({ properties: [propertyFilter] })
                })

                it('can filter partial properties inside the array', async () => {
                    const propertyFilter = makePropertyFilter()
                    const partialPropertyFilter = { type: 't' } as EmptyPropertyFilter
                    await expectLogic(logic, () => {
                        logic.actions.setProperties([propertyFilter, partialPropertyFilter])
                    }).toMatchValues({ properties: [propertyFilter] })
                })
            })
        })

        describe('the selectors', () => {
            it('can format events when there are events', async () => {
                const event = makeEvent()
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: [event], hasNext: false, isNext: false })
                }).toMatchValues({ eventsFormatted: [{ event }] })
            })

            it('can format events where there are new events', async () => {
                const event = makeEvent()
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: [event], hasNext: false, isNext: false })
                    logic.actions.pollEventsSuccess([makeEvent('2')])
                }).toMatchValues({ eventsFormatted: [{ new_events: true }, { event }] })
            })

            it('can format events to include day markers', async () => {
                const yesterday = makeEvent('yesterday', '2021-09-22T10:35:39.875Z')
                const today = makeEvent('today', '2021-09-23T10:35:39.875Z')
                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({ events: [today, yesterday], hasNext: false, isNext: false })
                }).toMatchValues({
                    eventsFormatted: [{ event: today }, { date_break: 'September 22, 2021' }, { event: yesterday }],
                })
            })
        })

        describe('url handling', () => {
            it('writes properties to the URL', async () => {
                const value = randomString()
                const propertyFilter = makePropertyFilter(value)
                logic.actions.setProperties([propertyFilter])
                expect(router.values.searchParams).toHaveProperty('properties', [propertyFilter])
            })

            it('does not write empty properties to the URL', async () => {
                logic.actions.setProperties([])
                expect(router.values.searchParams).not.toHaveProperty('properties')
            })

            it('reads properties from the URL', async () => {
                const propertyFilter = makePropertyFilter()
                router.actions.push(urls.events(), { properties: [propertyFilter] })
                await expectLogic(logic, () => {}).toMatchValues({ properties: [propertyFilter] })
            })

            it('writes event filter to the URL', async () => {
                const eventFilter = randomString()
                await expectLogic(logic, () => {
                    logic.actions.setEventFilter(eventFilter)
                })
                expect(router.values.searchParams).toHaveProperty('eventFilter', eventFilter)
            })

            it('fires two actions to change state, but just one API.get', async () => {
                ;(api.get as jest.Mock).mockClear() // because it will have been called on mount
                // Return a single event, so the logic doesn't make a second call
                // Normally, if the logic does not receive any event in the first call
                // it makes a second call with a longer time frame
                useMocks({
                    get: {
                        '/api/projects/:team/events/': { results: [{}], count: 1 },
                    },
                })
                await expectLogic(logic, () => {
                    const propertyFilter = makePropertyFilter()
                    router.actions.push(urls.events(), { properties: [propertyFilter], eventFilter: 'new event' })
                })
                    .toDispatchActions([
                        'setProperties',
                        'fetchEvents',
                        'setEventFilter',
                        'fetchEvents',
                        'fetchEventsSuccess',
                    ])
                    .toFinishAllListeners()
                expect(api.get).toHaveBeenCalledTimes(1)
            })
        })

        describe('polling for events', () => {
            it('starts active', async () => {
                await expectLogic(logic).toMatchValues({ pollingIsActive: true })
            })

            it('can pause polling for events', async () => {
                ;(api.get as jest.Mock).mockClear() // because it will have been called on mount

                await expectLogic(logic, () => {
                    logic.actions.setPollingActive(false)
                    logic.actions.pollEvents()
                }).toMatchValues({
                    pollingIsActive: false,
                })

                expect(api.get).not.toHaveBeenCalled()
            })

            it('can restart polling for events', async () => {
                ;(api.get as jest.Mock).mockClear() // because it will have been called on mount

                await expectLogic(logic, () => {
                    logic.actions.setPollingActive(false)
                    logic.actions.setPollingActive(true)
                    logic.actions.pollEvents()
                }).toMatchValues({
                    pollingIsActive: true,
                })

                expect(api.get).toHaveBeenCalled()
            })

            it('polling success pauses polling for events when there are events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setPollingActive(false)
                    logic.actions.setPollingActive(true)
                    logic.actions.pollEventsSuccess([makeEvent()])
                }).toMatchValues({
                    pollingIsActive: false,
                })
            })

            it('polling restarts when toggling automatic load', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setPollingActive(false)
                    logic.actions.toggleAutomaticLoad(true)
                }).toMatchValues({
                    pollingIsActive: true,
                })
            })

            it('polling success does not pause polling for events when there are not events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setPollingActive(false)
                    logic.actions.setPollingActive(true)
                    logic.actions.pollEventsSuccess([])
                }).toMatchValues({
                    pollingIsActive: true,
                })
            })

            it('viewing the new events restarts polling for events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setPollingActive(false)
                    logic.actions.setPollingActive(true)
                    logic.actions.pollEventsSuccess([makeEvent()])
                    logic.actions.prependNewEvents()
                }).toMatchValues({
                    pollingIsActive: true,
                })
            })
        })

        describe('the listeners', () => {
            it('triggers fetch events with no arguments on fetchNextEvents when there are no existing events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchNextEvents()
                }).toDispatchActions([logic.actionCreators.fetchEvents()])
            })

            it('calls prepend new when autoload is toggled and there are new events', async () => {
                const event = makeEvent('1', randomString())

                await expectLogic(logic, () => {
                    logic.actions.pollEventsSuccess([event])
                    logic.actions.toggleAutomaticLoad(true)
                }).toDispatchActions([logic.actionCreators.prependEvents([event])])
            })

            it('calls error toast on fetch failure', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchOrPollFailure({})
                })
                expect(errorToastSpy).toHaveBeenCalled()
            })

            it('can trigger CSV export', async () => {
                await expectLogic(logic, () => {
                    logic.actions.startDownload()
                })
                expect(triggerExport).toHaveBeenCalledWith({
                    export_context: {
                        max_limit: 3500,
                        path: `/api/projects/${MOCK_TEAM_ID}/events?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D`,
                    },
                    export_format: 'text/csv',
                })
            })
        })
    })
})
