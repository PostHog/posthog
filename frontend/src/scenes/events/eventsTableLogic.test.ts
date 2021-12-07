import { BuiltLogic } from 'kea'
import { eventsTableLogicType } from 'scenes/events/eventsTableLogicType'
import { ApiError, eventsTableLogic, EventsTableLogicProps, OnFetchEventsSuccess } from 'scenes/events/eventsTableLogic'
import { MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { router } from 'kea-router'
import * as utils from 'lib/utils'
import { EmptyPropertyFilter, EventType, PropertyFilter } from '~/types'
import { urls } from 'scenes/urls'

const errorToastSpy = jest.spyOn(utils, 'errorToast')
const successToastSpy = jest.spyOn(utils, 'successToast')

jest.mock('lib/api')

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
    operator: null,
    type: 't',
    value: 'v',
})

describe('eventsTableLogic', () => {
    let logic: BuiltLogic<eventsTableLogicType<ApiError, EventsTableLogicProps, OnFetchEventsSuccess>>

    mockAPI(async () => {
        // delay the API response so the default value test can complete before it
        await new Promise((resolve) => setTimeout(resolve, 0))
        return { results: [], count: 0 }
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

        it('does not show as scene is events', async () => {
            await expectLogic(logic).toMatchValues({
                sceneIsEventsPage: false,
            })
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
                sceneIsEventsPage: true,
            })
        })

        describe('reducers', () => {
            it('can toggle autoloading on', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleAutomaticLoad(true)
                }).toMatchValues({
                    automaticLoadEnabled: true,
                })
            })

            it('can toggle autoloading on and off', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleAutomaticLoad(true)
                    logic.actions.toggleAutomaticLoad(false)
                }).toMatchValues({
                    automaticLoadEnabled: false,
                })
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

            it('can check if scene is loaded when it is', async () => {
                await expectLogic(logic, () => {
                    router.actions.push(urls.events())
                }).toMatchValues({ sceneIsEventsPage: true })
            })

            it('can flip the sorting order', async () => {
                await expectLogic(logic, () => {
                    logic.actions.flipSort()
                }).toMatchValues({
                    orderBy: 'timestamp',
                })
            })

            it('can flip the sorting order back', async () => {
                await expectLogic(logic, () => {
                    logic.actions.flipSort()
                    logic.actions.flipSort()
                }).toMatchValues({
                    orderBy: '-timestamp',
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
                        logic.actions.fetchEvents({ events: [], hasNext: randomBool(), isNext: randomBool() })
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

            it('can build the export URL when there are no properties or filters', async () => {
                await expectLogic(logic, () => {}).toMatchValues({
                    exportUrl: `/api/projects/${MOCK_TEAM_ID}/events.csv?properties=%5B%5D&orderBy=%5B%22-timestamp%22%5D`,
                })
            })

            it('can build the export URL when there are properties or filters', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setProperties([makePropertyFilter('fixed value')])
                }).toMatchValues({
                    exportUrl: `/api/projects/${MOCK_TEAM_ID}/events.csv?properties=%5B%7B%22key%22%3A%22fixed%20value%22%2C%22operator%22%3Anull%2C%22type%22%3A%22t%22%2C%22value%22%3A%22v%22%7D%5D&orderBy=%5B%22-timestamp%22%5D`,
                })
            })

            it('can build the export URL when orderby changes', async () => {
                await expectLogic(logic, () => {
                    logic.actions.flipSort()
                }).toMatchValues({
                    exportUrl: `/api/projects/${MOCK_TEAM_ID}/events.csv?properties=%5B%5D&orderBy=%5B%22timestamp%22%5D`,
                })
            })
        })

        it('writes autoload toggle to the URL', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleAutomaticLoad(true)
            })
            expect(router.values.searchParams).toHaveProperty('autoload', true)
        })

        it('writes properties to the URL', async () => {
            const value = randomString()
            const propertyFilter = makePropertyFilter(value)
            await expectLogic(logic, () => {
                logic.actions.setProperties([propertyFilter])
            })
            expect(router.values.searchParams).toHaveProperty('properties', [propertyFilter])
        })

        it('reads autoload from the URL', async () => {
            router.actions.push(urls.events(), { autoload: true })
            await expectLogic(logic, () => {}).toMatchValues({ automaticLoadEnabled: true })
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

        describe('the listeners', () => {
            it('triggers fetch events on set properties', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setProperties([])
                }).toDispatchActions(['fetchEvents'])
            })

            it('triggers fetch events on flipsort', async () => {
                await expectLogic(logic, () => {
                    logic.actions.flipSort()
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
