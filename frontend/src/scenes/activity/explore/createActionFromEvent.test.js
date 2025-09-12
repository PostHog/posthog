import { api } from 'lib/api.mock'

import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { createActionFromEvent } from './createActionFromEvent'

describe('createActionFromEvent()', () => {
    given(
        'subject',
        () => () =>
            createActionFromEvent(
                given.teamId,
                given.event,
                given.increment,
                given.dataAttributes,
                given.createInFolder,
                given.recurse
            )
    )

    given('teamId', () => 44)
    given('increment', () => 0)
    given('dataAttributes', () => [])
    given('createInFolder', () => null)
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
        initKeaTests()
        jest.spyOn(api.actions, 'get')
        jest.spyOn(api.actions, 'create')
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

            expect(router.values.location.pathname).toEqual('/project/997/data-management/actions/456')
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

            describe('without data attributes', () => {
                given('eventType', () => 'submit')
                given('elements', () => [
                    { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                ])

                it('handles submit $autocapture events with elements', async () => {
                    await given.subject()

                    expect(api.actions.create).toHaveBeenCalledWith({
                        name: 'submitted form with text "Submit form!"',
                        steps: [
                            {
                                event: '$autocapture',
                                url: 'http://foo.bar/some/path',
                                url_matching: 'exact',
                                text: 'Submit form!',
                                properties: [{ key: '$event_type', operator: 'exact', type: 'event', value: 'submit' }],
                            },
                        ],
                    })
                })
            })

            describe('with data attributes', () => {
                given('eventType', () => 'click')
                given('elements', () => [
                    { tag_name: 'input', text: 'Submit form!' },
                    { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                ])
                given('dataAttributes', () => ['data-attr'])

                it('handles data attributes', async () => {
                    await given.subject()

                    expect(api.actions.create).toHaveBeenCalledWith({
                        name: 'clicked input with text "Submit form!"',
                        steps: [
                            {
                                event: '$autocapture',
                                url: 'http://foo.bar/some/path',
                                url_matching: 'exact',
                                href: undefined,
                                text: 'Submit form!',
                                selector: '[data-attr="form"] > input',
                            },
                        ],
                    })
                })
            })

            describe('with data attributes on a link', () => {
                given('eventType', () => 'click')
                given('elements', () => [
                    { tag_name: 'svg' },
                    { tag_name: 'a', text: 'Submit form via link!', attributes: { 'attr__data-attr': 'link' } },
                    { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                ])
                given('dataAttributes', () => ['data-attr'])

                it('handles data attributes', async () => {
                    await given.subject()

                    expect(api.actions.create).toHaveBeenCalledWith({
                        name: 'clicked svg',
                        steps: [
                            {
                                event: '$autocapture',
                                url: 'http://foo.bar/some/path',
                                url_matching: 'exact',
                                href: undefined,
                                text: undefined,
                                selector: '[data-attr="link"]',
                            },
                        ],
                    })
                })
            })

            describe('with wildcard data attributes', () => {
                given('eventType', () => 'click')
                given('elements', () => [
                    { tag_name: 'svg' },
                    { tag_name: 'a', text: 'Submit form via link!', attributes: { 'attr__data-attr': 'link' } },
                    { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                ])
                given('dataAttributes', () => ['data-at*'])

                it('handles data attributes', async () => {
                    await given.subject()

                    expect(api.actions.create).toHaveBeenCalledWith({
                        name: 'clicked svg',
                        steps: [
                            {
                                event: '$autocapture',
                                url: 'http://foo.bar/some/path',
                                url_matching: 'exact',
                                href: undefined,
                                text: undefined,
                                selector: '[data-attr="link"]',
                            },
                        ],
                    })
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
                throw { data: { type: 'validation_error', code: 'unique' } }
            })
        })

        it('recurses with increment + 1', async () => {
            await given.subject()

            expect(given.recurse).toHaveBeenCalledWith(
                given.teamId,
                given.event,
                1,
                given.dataAttributes,
                given.createInFolder,
                given.recurse
            )
        })

        describe('increment == 30', () => {
            given('increment', () => 30)

            it('stops recursion', async () => {
                await given.subject()

                expect(given.recurse).not.toHaveBeenCalled()
            })
        })
    })
})
