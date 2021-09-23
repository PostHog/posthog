import { BuiltLogic } from 'kea'
import { eventsTableLogicType } from 'scenes/events/eventsTableLogicType'
import { EventsTableEvent, eventsTableLogic, EventsTableLogicProps } from 'scenes/events/eventsTableLogic'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { truth } from '~/test/kea-test-utils/jest'
import { router } from 'kea-router'

jest.mock('lib/api')

const randomBool = (): boolean => Math.random() < 0.5

const randomString = (): string => Math.random().toString(36).substr(2, 5)

const makeEvent = (id: string = '1', timestamp: string = randomString()): EventsTableEvent => ({
    id: id,
    timestamp,
    action: { name: randomString(), id: randomString() },
})

describe('eventsTableLogic', () => {
    let logic: BuiltLogic<eventsTableLogicType<EventsTableEvent, EventsTableLogicProps>>

    mockAPI(async () => ({ results: [], count: 0 }))

    initKeaTestLogic({
        logic: eventsTableLogic,
        props: {
            key: 'test-key',
        },
        onLogic: (l) => (logic = l),
    })

    it('sets a key', () => {
        expect(logic.key).toEqual('all-events--test-key')
    })

    it('starts with known defaults', async () => {
        await expectLogic(logic).toMatchValues({
            initialPathname: '/',
            properties: expect.arrayContaining([]),
            eventFilter: '',
            isLoading: false,
            isLoadingNext: false,
            events: [],
            hasNext: false,
            orderBy: '-timestamp',
            selectedEvent: null,
            newEvents: [],
            highlightEvents: {},
            pollTimeout: truth((pt) => pt >= -1), //may not be default of -1 if the logic has already run a poll
            columnConfigSaving: false,
            automaticLoadEnabled: false,
            columnConfig: 'DEFAULT',
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
                logic.actions.pollEventsSuccess([{}, {}, {}])
                logic.actions.toggleAutomaticLoad(true)
            })
                .toMatchValues({
                    automaticLoadEnabled: true,
                })
                .toDispatchActions(['prependNewEvents'])
        })

        it('does not call prependNewEvents when there are new events but loading is off', async () => {
            await expectLogic(logic, () => {
                logic.actions.pollEventsSuccess([{}, {}, {}])
                logic.actions.toggleAutomaticLoad(false)
            }).toMatchValues({
                automaticLoadEnabled: false,
            })
        })

        it('can mark that column config is saving', async () => {
            await expectLogic(logic, () => {
                logic.actions.setColumnConfig(true)
            }).toMatchValues({
                columnConfigSaving: true,
            })
        })

        it('can set a poll timeout ID', async () => {
            await expectLogic(logic, () => {
                logic.actions.setPollTimeout(12)
            }).toMatchValues({
                pollTimeout: 12,
            })
        })

        it('can highlight new events', async () => {
            await expectLogic(logic, () => {
                logic.actions.prependNewEvents([{ id: 'potato' }])
            }).toMatchValues({
                highlightEvents: { potato: true },
            })
        })

        //TODO why does it?
        it('can clear highlighted events when poll is successful', async () => {
            await expectLogic(logic, () => {
                logic.actions.prependNewEvents([{ id: 'potato' }])
                logic.actions.pollEventsSuccess()
            }).toMatchValues({
                highlightEvents: {},
            })
        })

        it('sets new events when polling succeeds', async () => {
            const apiResponse = [{ id: 'potato' }]
            await expectLogic(logic, () => {
                logic.actions.pollEventsSuccess(apiResponse)
            }).toMatchValues({
                newEvents: apiResponse,
            })
        })

        it('clears new events when setting properties', async () => {
            const apiResponse = [{ id: 'potato' }]
            await expectLogic(logic, () => {
                logic.actions.pollEventsSuccess(apiResponse)
                logic.actions.setProperties([])
            }).toMatchValues({
                newEvents: [],
            })
        })

        it('clears new events when prepending new events', async () => {
            const apiResponse = [{ id: 'potato' }]
            await expectLogic(logic, () => {
                logic.actions.pollEventsSuccess(apiResponse)
                logic.actions.prependNewEvents([])
            }).toMatchValues({
                newEvents: [],
            })
        })

        // TODO but nothing uses this action
        it('can select an event', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSelectedEvent({ id: 4 })
            }).toMatchValues({
                selectedEvent: expect.objectContaining({ id: 4 }),
            })
        })

        it('can flip the sorting order', async () => {
            await expectLogic(logic, () => {
                logic.actions.flipSort('-timestamp')
            }).toMatchValues({
                orderBy: 'timestamp',
            })
        })

        it('can flip the sorting order back', async () => {
            await expectLogic(logic, () => {
                logic.actions.flipSort('-timestamp')
                logic.actions.flipSort('timestamp')
            }).toMatchValues({
                orderBy: '-timestamp',
            })
        })

        it('fetch events success can set hasNext (which is the URL of the next page of results, that we do not use)', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchEventsSuccess({ events: '', hasNext: true, isNext: false })
            }).toMatchValues({
                hasNext: true,
            })
        })

        it('fetch events clears the has next flag', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchEventsSuccess({ events: '', hasNext: true, isNext: false })
                logic.actions.fetchEvents()
            }).toMatchValues({
                hasNext: false,
            })
        })

        it('fetch next events clears the has next flag', async () => {
            await expectLogic(logic, () => {
                logic.actions.fetchEventsSuccess({ events: '', hasNext: true, isNext: false })
                logic.actions.fetchNextEvents()
            }).toMatchValues({
                hasNext: false,
            })
        })

        it('sets events when preprendNewEvents is called', async () => {
            const events = [{ id: 'potato' }, { id: 'tomato' }]
            await expectLogic(logic, () => {
                logic.actions.prependNewEvents(events)
            }).toMatchValues({
                events,
            })
        })

        it('replaces events when not loading a new "page"', async () => {
            const originalEvents = [{ id: 'potato' }, { id: 'tomato' }]
            const subsequentEvents = [{ id: 'apple' }, { id: 'melon' }]
            await expectLogic(logic, () => {
                logic.actions.fetchEventsSuccess({ events: originalEvents, hasNext: false, isNext: false })
                logic.actions.fetchEventsSuccess({ events: subsequentEvents, hasNext: false, isNext: false })
            }).toMatchValues({
                events: subsequentEvents,
            })
        })

        it('adds events when loading a new "page"', async () => {
            const originalEvents = [{ id: 'potato' }, { id: 'tomato' }]
            const subsequentEvents = [{ id: 'apple' }, { id: 'melon' }]
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
            // had complicated implementation but on testing the fetchEvents action maintains the current state

            it('simple cases', async () => {
                await expectLogic(logic).toMatchValues({ isLoading: false })
                await expectLogic(logic, () => {
                    logic.actions.setDelayedLoading()
                }).toMatchValues({ isLoading: true })
                await expectLogic(logic, () => {
                    logic.actions.setDelayedLoading()
                    logic.actions.fetchEventsSuccess({ events: [], hasNext: randomBool(), isNext: randomBool() })
                }).toMatchValues({ isLoading: false })
                await expectLogic(logic, () => {
                    logic.actions.setDelayedLoading()
                    logic.actions.fetchOrPollFailure(new Error())
                }).toMatchValues({ isLoading: false })
            })

            it('on FetchEvents remains true when next params is true', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setDelayedLoading() // now it is true
                    logic.actions.fetchEvents({ events: [], hasNext: randomBool(), isNext: randomBool() })
                }).toMatchValues({ isLoading: true })
            })

            it('on FetchEvents remains false when next params is true', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchEvents({ events: [], hasNext: randomBool(), isNext: randomBool() })
                }).toMatchValues({ isLoading: false })
            })

            it('on FetchEvents remains true when next params is false', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setDelayedLoading() // now it is true
                    logic.actions.fetchEvents({ events: [], hasNext: randomBool(), isNext: randomBool() })
                }).toMatchValues({ isLoading: true })
            })

            it('on FetchEvents remains false when next params is false', async () => {
                await expectLogic(logic, () => {
                    logic.actions.fetchEvents({ events: [], hasNext: randomBool(), isNext: randomBool() })
                }).toMatchValues({ isLoading: false })
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
                }).toMatchValues({ properties: [{}] })

                await expectLogic(logic, () => {
                    logic.actions.setProperties({})
                }).toMatchValues({ properties: [{}] })

                await expectLogic(logic, () => {
                    logic.actions.setProperties([{}])
                }).toMatchValues({ properties: [{}] })
            })

            it('can set an object inside the array', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setProperties([{ key: 'value' }])
                }).toMatchValues({ properties: [{ key: 'value' }] })
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
                exportUrl: '/api/event.csv?properties=%5B%7B%7D%5D&orderBy=%5B%22-timestamp%22%5D',
            })
        })

        it('can build the export URL when there are properties or filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setProperties([{ key: 'value' }])
            }).toMatchValues({
                exportUrl:
                    '/api/event.csv?properties=%5B%7B%22key%22%3A%22value%22%7D%5D&orderBy=%5B%22-timestamp%22%5D',
            })
        })

        it('can build the export URL when orderby changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.flipSort()
            }).toMatchValues({
                exportUrl: '/api/event.csv?properties=%5B%7B%7D%5D&orderBy=%5B%22timestamp%22%5D',
            })
        })

        // TODO test columnConfig reads from userLogic

        it('writes autoload toggle to the URL', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleAutomaticLoad(true)
            })
            expect(router.values.searchParams).toHaveProperty('autoload', true)
        })

        it('writes properties to the URL', async () => {
            const value = randomString()
            await expectLogic(logic, () => {
                logic.actions.setProperties([{ key: value }])
            })
            expect(router.values.searchParams).toHaveProperty('properties', [{ key: value }])
        })

        it('reads autoload from the URL', async () => {
            router.actions.push(router.values.location.pathname, { autoload: true })
            await expectLogic(logic, () => {}).toMatchValues({ automaticLoadEnabled: true })
        })

        it('reads properties from the URL', async () => {
            const value = randomString()
            router.actions.push(router.values.location.pathname, { properties: [{ key: value }] })
            await expectLogic(logic, () => {}).toMatchValues({ properties: [{ key: value }] })
        })
    })
})
