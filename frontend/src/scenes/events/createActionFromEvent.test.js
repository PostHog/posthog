import api from 'lib/api'
import { router } from 'kea-router'
import { toast } from 'react-toastify'
import { createActionFromEvent } from './createActionFromEvent'

jest.mock('lib/api')
jest.mock('react-toastify')
jest.mock('kea-router', () => ({
    router: { actions: { push: jest.fn() } },
}))

describe('createActionFromEvent()', () => {
    given('subject', () => () => createActionFromEvent(given.teamId, given.event, given.increment, given.recurse))

    given('teamId', () => 44)
    given('increment', () => 0)
    given('recurse', () => jest.fn())

    given('event', () => ({
        id: 123,
        event: given.eventName,
        properties: {
            $current_url: 'http://foo.bar/some/path',
            $event_type: given.eventType,
        },
        elements: given.elements,
    }))

    given('eventName', () => 'some-event')
    given('elements', () => [])
    given('createResponse', () => ({ id: 456 }))

    beforeEach(() => {
        api.actions.get.mockImplementation(() => Promise.resolve(given.event))
        api.actions.create.mockImplementation(() => Promise.resolve(given.createResponse))
    })

    describe('action did not exist', () => {
        it('creates the correct action', async () => {
            await given.subject()

            expect(api.actions.create).toHaveBeenCalledWith({
                name: 'some-event event',
                steps: [{ event: 'some-event' }],
            })
        })

        it('directs to the action page and shows toast', async () => {
            await given.subject()

            expect(router.actions.push).toHaveBeenCalledWith('/action/456')
            expect(toast.mock.calls).toMatchSnapshot()
        })

        describe('increments', () => {
            given('increment', () => 4)

            it('handles increments', async () => {
                await given.subject()

                expect(api.actions.create).toHaveBeenCalledWith({
                    name: 'some-event event 4',
                    steps: [{ event: 'some-event' }],
                })
            })
        })

        describe('$autocapture events', () => {
            given('eventName', () => '$autocapture')
            given('eventType', () => 'submit')
            given('elements', () => [{ tag_name: 'form', text: 'Submit form!' }, {}])

            it('handles submit $autocapture events with elements', async () => {
                await given.subject()

                expect(api.actions.create).toHaveBeenCalledWith({
                    name: 'submitted form with text "Submit form!"',
                    steps: [
                        {
                            event: '$autocapture',
                            url: 'http://foo.bar/some/path',
                            url_matching: 'exact',
                            tag_name: 'form',
                            text: 'Submit form!',
                            properties: [{ key: '$event_type', value: 'submit' }],
                        },
                    ],
                })
            })
        })

        describe('$pageview event', () => {
            given('eventName', () => '$pageview')

            it('is handled', async () => {
                await given.subject()

                expect(api.actions.create).toHaveBeenCalledWith({
                    name: 'Pageview on /some/path',
                    steps: [{ event: '$pageview', url: 'http://foo.bar/some/path', url_matching: 'exact' }],
                })
            })
        })
    })

    describe('action already exists', () => {
        beforeEach(() => {
            api.actions.create.mockImplementation(() => {
                throw { type: 'validation_error', code: 'unique' }
            })
        })

        it('recurses with increment + 1', async () => {
            await given.subject()

            expect(given.recurse).toHaveBeenCalledWith(given.teamId, given.event, 1, given.recurse)
            expect(toast).not.toHaveBeenCalled()
        })

        describe('increment == 30', () => {
            given('increment', () => 30)

            it('stops recursion', async () => {
                await given.subject()

                expect(given.recurse).not.toHaveBeenCalled()
                expect(toast).not.toHaveBeenCalled()
            })
        })
    })
})
