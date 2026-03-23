import { api } from 'lib/api.mock'

import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { createActionFromEvent } from './createActionFromEvent'

describe('createActionFromEvent()', () => {
    const teamId = 44
    const createInFolder = null
    const recurse = jest.fn()

    const makeEvent = (overrides = {}) => ({
        id: 123,
        event: 'some-event',
        properties: {
            $current_url: 'http://foo.bar/some/path',
            $event_type: undefined,
        },
        elements: [],
        ...overrides,
    })

    const subject = (event, increment = 0, dataAttributes = []) =>
        createActionFromEvent(teamId, event, increment, dataAttributes, createInFolder, recurse)

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.actions, 'get')
        jest.spyOn(api.actions, 'create')
        api.actions.create.mockImplementation(() => Promise.resolve({ id: 456 }))
    })

    describe('action did not exist', () => {
        it('creates the correct action', async () => {
            const event = makeEvent()
            api.actions.get.mockImplementation(() => Promise.resolve(event))

            await subject(event)

            expect(api.actions.create).toHaveBeenCalledWith({
                name: 'some-event event',
                steps: [{ event: 'some-event' }],
            })
        })

        it('directs to the action page and shows toast', async () => {
            const event = makeEvent()
            api.actions.get.mockImplementation(() => Promise.resolve(event))

            await subject(event)

            expect(router.values.location.pathname).toEqual('/project/997/data-management/actions/456')
        })

        describe('increments', () => {
            it('handles increments', async () => {
                const event = makeEvent()
                api.actions.get.mockImplementation(() => Promise.resolve(event))

                await subject(event, 4)

                expect(api.actions.create).toHaveBeenCalledWith({
                    name: 'some-event event 4',
                    steps: [{ event: 'some-event' }],
                })
            })
        })

        describe('$autocapture events', () => {
            describe('without data attributes', () => {
                it('handles submit $autocapture events with elements', async () => {
                    const event = makeEvent({
                        event: '$autocapture',
                        properties: {
                            $current_url: 'http://foo.bar/some/path',
                            $event_type: 'submit',
                        },
                        elements: [
                            { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                        ],
                    })
                    api.actions.get.mockImplementation(() => Promise.resolve(event))

                    await subject(event)

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
                it('handles data attributes', async () => {
                    const event = makeEvent({
                        event: '$autocapture',
                        properties: {
                            $current_url: 'http://foo.bar/some/path',
                            $event_type: 'click',
                        },
                        elements: [
                            { tag_name: 'input', text: 'Submit form!' },
                            { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                        ],
                    })
                    api.actions.get.mockImplementation(() => Promise.resolve(event))

                    await subject(event, 0, ['data-attr'])

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
                it('handles data attributes', async () => {
                    const event = makeEvent({
                        event: '$autocapture',
                        properties: {
                            $current_url: 'http://foo.bar/some/path',
                            $event_type: 'click',
                        },
                        elements: [
                            { tag_name: 'svg' },
                            { tag_name: 'a', text: 'Submit form via link!', attributes: { 'attr__data-attr': 'link' } },
                            { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                        ],
                    })
                    api.actions.get.mockImplementation(() => Promise.resolve(event))

                    await subject(event, 0, ['data-attr'])

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
                it('handles data attributes', async () => {
                    const event = makeEvent({
                        event: '$autocapture',
                        properties: {
                            $current_url: 'http://foo.bar/some/path',
                            $event_type: 'click',
                        },
                        elements: [
                            { tag_name: 'svg' },
                            { tag_name: 'a', text: 'Submit form via link!', attributes: { 'attr__data-attr': 'link' } },
                            { tag_name: 'form', text: 'Submit form!', attributes: { 'attr__data-attr': 'form' } },
                        ],
                    })
                    api.actions.get.mockImplementation(() => Promise.resolve(event))

                    await subject(event, 0, ['data-at*'])

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
            it('is handled', async () => {
                const event = makeEvent({ event: '$pageview' })
                api.actions.get.mockImplementation(() => Promise.resolve(event))

                await subject(event)

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
            const event = makeEvent()
            api.actions.get.mockImplementation(() => Promise.resolve(event))

            await subject(event)

            expect(recurse).toHaveBeenCalledWith(teamId, event, 1, [], createInFolder, recurse)
        })

        describe('increment == 30', () => {
            it('stops recursion', async () => {
                const event = makeEvent()
                api.actions.get.mockImplementation(() => Promise.resolve(event))

                await subject(event, 30)

                expect(recurse).not.toHaveBeenCalled()
            })
        })
    })
})
