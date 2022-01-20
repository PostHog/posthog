import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import * as utils from 'lib/utils'
import { EmptyPropertyFilter, EventType, PropertyFilter, PropertyOperator } from '~/types'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const errorToastSpy = jest.spyOn(utils, 'errorToast')
const successToastSpy = jest.spyOn(utils, 'successToast')

jest.mock('lib/api')

const nowForMock = '2021-05-05T00:00:00.000Z'
jest.mock('lib/dayjs', () => {
    const dayjs = jest.requireActual('lib/dayjs')
    return { ...dayjs, now: () => dayjs.dayjs(nowForMock) }
})

const randomBool = (): boolean => Math.random() < 0.5

const randomString = (): string => Math.random().toString(36).substr(2, 5)

const makeEvent = (id: string = '1', timestamp: string = randomString()): EventType => ({
    id: id,
    timestamp,
    elements: [],
    elements_hash: '',
    event: '',
    properties: {},
})

// TODO test interactions with userLogic

const makePropertyFilter = (value: string = randomString()): PropertyFilter => ({
    key: value,
    operator: PropertyOperator.Exact,
    type: 't',
    value: 'v',
})

const filterAfterOneYearAgo = {
    key: '$time',
    operator: PropertyOperator.IsDateAfter,
    type: 'event',
    value: '-365d',
}

describe('eventsTableLogic', () => {
    let logic: ReturnType<typeof eventsTableLogic.build>

    mockAPI(async () => {
        // delay the API response so the default value test can complete before it
        await new Promise((resolve) => setTimeout(resolve, 0))
        return { results: [], count: 0 }
    })

    describe('when polling is disabled', () => {
        initKeaTestLogic({
            logic: eventsTableLogic,
            props: {
                key: 'test-key',
                sceneUrl: urls.person('1'),
                disableActions: true,
            },
            onLogic: (l) => (logic = l),
            beforeLogic: () => {
                router.actions.push(urls.person('1'))
            },
        })

        it('can disable polling for events', async () => {
            ;(api.get as jest.Mock).mockClear() // because it will have been called on mount

            await expectLogic(logic, () => {
                logic.actions.setPollingActive(true) // even with polling active
                logic.actions.pollEvents()
            })

            expect(api.get).not.toHaveBeenCalled()
        })
    })

    describe('when loaded on a different page', () => {
        initKeaTestLogic({
            logic: eventsTableLogic,
            props: {
                key: 'test-key',
                sceneUrl: urls.person('1'),
            },
            onLogic: (l) => (logic = l),
            beforeLogic: () => {
                router.actions.push(urls.person('1'))
            },
        })
    })

    describe('when loaded on events page', () => {
        initKeaTestLogic({
            logic: eventsTableLogic,
            props: {
                key: 'test-key',
                sceneUrl: urls.events(),
            },
            onLogic: (l) => (logic = l),
            beforeLogic: () => {
                router.actions.push(urls.events())
            },
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

        describe('limiting the loaded data size with URL params', () => {
            const firstEvent = makeEvent('1', 'the first timestamp')
            const secondEvent = makeEvent('1', 'the second timestamp')
            const eventsUrlWithIsDateAfterFilter = `api/projects/${MOCK_TEAM_ID}/events/?properties=%5B%7B%22key%22%3A%22%24time%22%2C%22operator%22%3A%22is_date_after%22%2C%22type%22%3A%22event%22%2C%22value%22%3A%22-365d%22%7D%5D&orderBy=%5B%22-timestamp%22%5D`

            describe('when the QUERY_EVENTS_BY_DATETIME flag is on', () => {
                let dateFlagOnLogic: ReturnType<typeof eventsTableLogic.build>
                initKeaTestLogic({
                    logic: eventsTableLogic,
                    props: {
                        key: 'test-key-date-querying-flagged-on',
                        sceneUrl: urls.events(),
                    },
                    onLogic: (l) => (dateFlagOnLogic = l),
                    beforeLogic: () => {
                        featureFlagLogic.mount()
                        const variants = {}
                        variants[FEATURE_FLAGS.QUERY_EVENTS_BY_DATETIME] = true
                        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.QUERY_EVENTS_BY_DATETIME], variants)
                        router.actions.push(urls.events())
                    },
                })

                it('starts a year before "now"', async () => {
                    await expectLogic(dateFlagOnLogic)
                        .toFinishAllListeners()
                        .toMatchValues({
                            properties: [filterAfterOneYearAgo],
                        })
                })

                it('adds property filter not the after parameter when polling against an empty set of events', async () => {
                    await expectLogic(dateFlagOnLogic, () => {})
                        .toFinishAllListeners()
                        .toMatchValues({ events: [] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOnLogic.actions.pollEvents()

                    expect(api.get).toHaveBeenCalledWith(eventsUrlWithIsDateAfterFilter)
                })

                it('does not remove one year time restriction when setting empty properties', async () => {
                    await expectLogic(dateFlagOnLogic, () => {
                        dateFlagOnLogic.actions.setProperties([])
                    }).toMatchValues({
                        properties: [filterAfterOneYearAgo],
                    })

                    await expectLogic(dateFlagOnLogic, () => {
                        dateFlagOnLogic.actions.setProperties([{} as any])
                    }).toMatchValues({ properties: [filterAfterOneYearAgo] })
                })

                it('sets the after parameter to the first timestamp when polling and holding events', async () => {
                    await expectLogic(dateFlagOnLogic, () => {
                        dateFlagOnLogic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                    }).toMatchValues({ events: [firstEvent, secondEvent] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOnLogic.actions.pollEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/' +
                            '?properties=%5B%7B%22key%22%3A%22%24time%22%2C%22operator%22%3A%22is_date_after%22%2C%22type%22%3A%22event%22%2C%22value%22%3A%22-365d%22%7D%5D' +
                            '&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=the%20first%20timestamp'
                    )
                })

                it('does not set the before parameter when fetching next events and holding no events', async () => {
                    await expectLogic(dateFlagOnLogic, () => {})
                        .toFinishAllListeners()
                        .toMatchValues({ events: [] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOnLogic.actions.fetchNextEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/' +
                            '?properties=%5B%7B%22key%22%3A%22%24time%22%2C%22operator%22%3A%22is_date_after%22%2C%22type%22%3A%22event%22%2C%22value%22%3A%22-365d%22%7D%5D' +
                            '&orderBy=%5B%22-timestamp%22%5D'
                    )
                })

                it('sets the before parameter to the last event timestamp when fetching next events and holding events', async () => {
                    await expectLogic(dateFlagOnLogic, () => {
                        dateFlagOnLogic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                    }).toMatchValues({ events: [firstEvent, secondEvent] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOnLogic.actions.fetchNextEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/' +
                            '?properties=%5B%7B%22key%22%3A%22%24time%22%2C%22operator%22%3A%22is_date_after%22%2C%22type%22%3A%22event%22%2C%22value%22%3A%22-365d%22%7D%5D' +
                            '&orderBy=%5B%22-timestamp%22%5D' +
                            '&before=the%20second%20timestamp'
                    )
                })

                it('can build the export URL when there are no properties or filters', async () => {
                    await expectLogic(dateFlagOnLogic, () => {}).toMatchValues({
                        exportUrl:
                            `/api/projects/${MOCK_TEAM_ID}/events.csv` +
                            '?properties=%5B%7B%22key%22%3A%22%24time%22%2C%22operator%22%3A%22is_date_after%22%2C%22type%22%3A%22event%22%2C%22value%22%3A%22-365d%22%7D%5D' +
                            '&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=2020-05-05T00%3A00%3A00.000Z',
                    })
                })

                it('can build the export URL when there are properties or filters', async () => {
                    await expectLogic(dateFlagOnLogic, () => {
                        dateFlagOnLogic.actions.setProperties([makePropertyFilter('fixed value')])
                    }).toMatchValues({
                        exportUrl:
                            `/api/projects/${MOCK_TEAM_ID}/events.csv` +
                            '?properties=%5B%7B%22key%22%3A%22%24time%22%2C%22operator%22%3A%22is_date_after%22%2C%22type%22%3A%22event%22%2C%22value%22%3A%22-365d%22%7D%2C%7B%22key%22%3A%22fixed%20value%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22t%22%2C%22value%22%3A%22v%22%7D%5D' +
                            '&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=2020-05-05T00%3A00%3A00.000Z',
                    })
                })

                it('can not pinned property', async () => {
                    const firstFilter = makePropertyFilter('fixed value')
                    const secondFilter = makePropertyFilter('another value')
                    await expectLogic(dateFlagOnLogic, () => {
                        dateFlagOnLogic.actions.setProperties([firstFilter])
                        dateFlagOnLogic.actions.setProperties([firstFilter, secondFilter])
                        dateFlagOnLogic.actions.setProperties([secondFilter])
                        dateFlagOnLogic.actions.setProperties([])
                    }).toMatchValues({
                        properties: [filterAfterOneYearAgo],
                    })
                })
            })

            describe('when the QUERY_EVENTS_BY_DATETIME flag is off', () => {
                let dateFlagOffLogic: ReturnType<typeof eventsTableLogic.build>
                initKeaTestLogic({
                    logic: eventsTableLogic,
                    props: {
                        key: 'test-key-date-querying-flagged-off',
                        sceneUrl: urls.events(),
                    },
                    onLogic: (l) => (dateFlagOffLogic = l),
                    beforeLogic: () => {
                        featureFlagLogic.mount()
                        const variants = {}
                        variants[FEATURE_FLAGS.QUERY_EVENTS_BY_DATETIME] = false
                        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.QUERY_EVENTS_BY_DATETIME], variants)
                        router.actions.push(urls.events())
                    },
                })

                it('starts a year before "now"', async () => {
                    await expectLogic(dateFlagOffLogic).toFinishAllListeners().toMatchValues({
                        properties: [],
                    })
                })

                it('sets the after parameter to a year ago when polling against an empty set of events', async () => {
                    await expectLogic(dateFlagOffLogic, () => {})
                        .toFinishAllListeners()
                        .toMatchValues({ events: [] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOffLogic.actions.pollEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=2020-05-05T00%3A00%3A00.000Z'
                    )
                })

                it('sets the after parameter to the first timestamp when polling and holding events', async () => {
                    await expectLogic(dateFlagOffLogic, () => {
                        dateFlagOffLogic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                    }).toMatchValues({ events: [firstEvent, secondEvent] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOffLogic.actions.pollEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=the%20first%20timestamp'
                    )
                })

                it('does not set the before parameter when fetching next events and holding no events', async () => {
                    await expectLogic(dateFlagOffLogic, () => {})
                        .toFinishAllListeners()
                        .toMatchValues({ events: [] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOffLogic.actions.fetchNextEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=2020-05-05T00%3A00%3A00.000Z'
                    )
                })

                it('sets the before parameter to the last event timestamp when fetching next events and holding events', async () => {
                    await expectLogic(dateFlagOffLogic, () => {
                        dateFlagOffLogic.actions.fetchEventsSuccess({
                            events: [firstEvent, secondEvent],
                            hasNext: false,
                            isNext: false,
                        })
                    }).toMatchValues({ events: [firstEvent, secondEvent] })
                    ;(api.get as jest.Mock).mockClear()

                    dateFlagOffLogic.actions.fetchNextEvents()

                    expect(api.get).toHaveBeenCalledWith(
                        'api/projects/997/events/?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D' +
                            '&before=the%20second%20timestamp' +
                            '&after=the%20first%20timestamp'
                    )
                })

                it('can build the export URL when there are no properties or filters', async () => {
                    await expectLogic(dateFlagOffLogic, () => {}).toMatchValues({
                        exportUrl:
                            `/api/projects/${MOCK_TEAM_ID}/events.csv` +
                            '?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D&after=2020-05-05T00%3A00%3A00.000Z',
                    })
                })

                it('can build the export URL when there are properties or filters', async () => {
                    await expectLogic(dateFlagOffLogic, () => {
                        dateFlagOffLogic.actions.setProperties([makePropertyFilter('fixed value')])
                    }).toMatchValues({
                        exportUrl:
                            `/api/projects/${MOCK_TEAM_ID}/events.csv` +
                            '?properties=%5B%7B%22key%22%3A%22fixed%20value%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22t%22%2C%22value%22%3A%22v%22%7D%5D&orderBy=%5B%22-timestamp%22%5D' +
                            '&after=2020-05-05T00%3A00%3A00.000Z',
                    })
                })

                it('can remove all properties', async () => {
                    const firstFilter = makePropertyFilter('fixed value')
                    const secondFilter = makePropertyFilter('another value')
                    await expectLogic(dateFlagOffLogic, () => {
                        dateFlagOffLogic.actions.setProperties([firstFilter])
                        dateFlagOffLogic.actions.setProperties([firstFilter, secondFilter])
                        dateFlagOffLogic.actions.setProperties([secondFilter])
                        dateFlagOffLogic.actions.setProperties([])
                    }).toMatchValues({
                        properties: [],
                    })
                })
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

                it('set delayed loading sets isloading to true', async () => {
                    await expectLogic(logic, () => {
                        logic.actions.fetchOrPollFailure({})
                        logic.actions.setDelayedLoading()
                    }).toMatchValues({ isLoading: true })
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
                describe('when query by date feature flag is off', () => {
                    it('can set empty properties when the query by date flag is off', async () => {
                        const variants = {}
                        variants[FEATURE_FLAGS.QUERY_EVENTS_BY_DATETIME] = false

                        await expectLogic(logic, () => {
                            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.QUERY_EVENTS_BY_DATETIME], variants)
                            logic.actions.setProperties([])
                        }).toMatchValues({ properties: [] })

                        await expectLogic(logic, () => {
                            logic.actions.setProperties([{} as any])
                        }).toMatchValues({ properties: [] })
                    })
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

        it('writes properties to the URL', async () => {
            const value = randomString()
            const propertyFilter = makePropertyFilter(value)
            await expectLogic(logic, () => {
                logic.actions.setProperties([propertyFilter])
            })
            expect(router.values.searchParams).toHaveProperty('properties', [propertyFilter])
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
        })

        describe('the listeners', () => {
            it('triggers fetch events on set properties', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setProperties([])
                }).toDispatchActions(['fetchEvents'])
            })

            it('triggers fetch events on set event filter', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setEventFilter(randomString())
                }).toDispatchActions(['fetchEvents'])
            })

            it('triggers fetch events with no arguments on fetchNextEvents when there are no existing events', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchNextEvents()
                }).toDispatchActions([logic.actionCreators.fetchEvents()])
            })

            it('triggers fetch events with before timestamp on fetchNextEvents when there are existing events', async () => {
                const event = makeEvent('1', randomString())

                await expectLogic(logic, () => {
                    logic.actions.fetchEventsSuccess({
                        events: [event],
                        hasNext: false,
                        isNext: false,
                    })
                    logic.actions.fetchNextEvents()
                }).toDispatchActions([logic.actionCreators.fetchEvents({ before: event.timestamp })])
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

            it('gives the user advice about the events export download', async () => {
                window = Object.create(window)
                Object.defineProperty(window, 'location', {
                    value: {
                        href: 'https://dummy.com',
                    },
                    writable: true,
                })

                await expectLogic(logic, () => {
                    logic.actions.startDownload()
                })
                expect(successToastSpy).toHaveBeenCalled()
            })
        })
    })
})
