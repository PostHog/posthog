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
    given('subject', () => () => createActionFromEvent(given.event, given.increment, given.recurse))

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
        api.get.mockImplementation(() => Promise.resolve(given.event))
        api.create.mockImplementation(() => Promise.resolve(given.createResponse))
    })

    describe('action did not exist', () => {
        it('creates the correct action', async () => {
            await given.subject()

            expect(api.create).toHaveBeenCalledWith('api/action', {
                name: 'some-event event',
                steps: [{ event: 'some-event', url: 'http://foo.bar/some/path', url_matching: 'exact' }],
            })
        })

        it('directs to the action page and shows toast', async () => {
            await given.subject()

            expect(router.actions.push).toHaveBeenCalledWith('/action/456')
            expect(toast.mock.calls).toMatchSnapshot()
        })

        it('handles increments', async () => {
            given('increment', () => 4)

            await given.subject()

            expect(api.create).toHaveBeenCalledWith('api/action', {
                name: 'some-event event 4',
                steps: [{ event: 'some-event', url: 'http://foo.bar/some/path', url_matching: 'exact' }],
            })
        })

        it('handles submit $autocapture events with elements', async () => {
            given('eventName', () => '$autocapture')
            given('eventType', () => 'submit')
            given('elements', () => [{ tag_name: 'form', text: 'Submit form!' }, {}])

            await given.subject()

            expect(api.create).toHaveBeenCalledWith('api/action', {
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

        it('handles $pageview events', async () => {
            given('eventName', () => '$pageview')

            await given.subject()

            expect(api.create).toHaveBeenCalledWith('api/action', {
                name: 'Pageview on /some/path',
                steps: [{ event: '$pageview', url: 'http://foo.bar/some/path', url_matching: 'exact' }],
            })
        })
    })

    describe('action already exists', () => {
        beforeEach(() => {
            api.create.mockImplementation(() => {
                throw { detail: 'action-exists' }
            })
        })

        it('recurses with increment + 1', async () => {
            await given.subject()

            expect(given.recurse).toHaveBeenCalledWith(given.event, 1, given.recurse)
            expect(toast).not.toHaveBeenCalled()
        })

        it('stops recursion if increment == 30', async () => {
            given('increment', () => 30)

            await given.subject()

            expect(given.recurse).not.toHaveBeenCalled()
            expect(toast).not.toHaveBeenCalled()
        })
    })
})
