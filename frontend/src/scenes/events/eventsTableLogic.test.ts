import { BuiltLogic } from 'kea'
import { eventsTableLogicType } from 'scenes/events/eventsTableLogicType'
import { EventsTableEvent, eventsTableLogic, EventsTableLogicProps } from 'scenes/events/eventsTableLogic'
import { mockAPI } from 'lib/api.mock'
import { mockEventDefinitions } from '~/test/mocks'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { truth } from '~/test/kea-test-utils/jest'

jest.mock('lib/api')

const randomBool = (): boolean => Math.random() < 0.5

describe('eventsTableLogic', () => {
    let logic: BuiltLogic<eventsTableLogicType<EventsTableEvent, EventsTableLogicProps>>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/projects/@current/event_definitions') {
            const results = searchParams.search
                ? mockEventDefinitions.filter((e) => e.name.includes(searchParams.search))
                : mockEventDefinitions
            return {
                results,
                count: results.length,
            }
        }
        // console.log({ pathname, searchParams }, 'mockAPI')
        return { results: [], count: 0 }
    })

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
})
