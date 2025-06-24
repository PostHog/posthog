import { RetryError } from '@posthog/plugin-scaffold'

import { onEvent } from './index'

const captureHost = 'localhost:8000'

const config = {
    host: captureHost,
    project_api_key: 'test',
    replication: 1,
    events_to_ignore: 'my-event-alpha, my-event-beta, my-event-gamma',
}

const mockEvent = require('./data/event.json')
const mockAutocaptureEvent = require('./data/autocapture-event.json')
const mockEventsToIgnore = require('./data/events-to-ignore.json')

const logger = {
    error: jest.fn(),
    log: jest.fn(),
    warn: jest.fn(),
    debug: jest.fn(),
}

describe('Replicator: onEvent', () => {
    const fetchMock = jest.fn()
    const mockResponse = (response: any, status: number = 200) => {
        fetchMock.mockResolvedValue({
            status: status,
            json: () => Promise.resolve(response),
            ok: status >= 200 && status < 300,
            statusText: status >= 400 ? 'Bad Request' : 'OK',
        })
    }

    beforeEach(() => {
        fetchMock.mockReset()
        mockResponse({})
    })

    describe('event pre-processing', () => {
        it('should handle a single event', async () => {
            mockResponse({})
            await onEvent(mockEvent, { config, logger, fetch: fetchMock } as any)

            expect(fetchMock.mock.calls[0][1]).toEqual({
                body: JSON.stringify([
                    {
                        distinct_id: '1234',
                        event: 'my-event',
                        properties: {
                            $ip: '127.0.0.1',
                            foo: 'bar',
                        },
                        token: 'test',
                    },
                ]),
                headers: {
                    'Content-Type': 'application/json',
                },
                method: 'POST',
            })
        })

        it('should skip ignored events', async () => {
            mockResponse({})
            for (const event of mockEventsToIgnore) {
                await onEvent(event, { config, logger, fetch: fetchMock } as any)
            }
            expect(fetchMock.mock.calls.length).toBe(0)
            await onEvent(mockEvent, { config, logger, fetch: fetchMock } as any)
            expect(fetchMock.mock.calls.length).toBe(1)
        })

        it('should reuse the values for timestamp, event, uuid', async () => {
            // This is important to ensure that we end up sending the correct
            // values for the properties that we dedup.
            // NOTE: we should be reasonably confident that these are the
            // values we'd receive as per the functional test here:
            // https://github.com/PostHog/posthog/blob/771691e8bdd6bf4465887b88d0a6019c9b4b91d6/plugin-server/functional_tests/exports-v2.test.ts#L151

            await onEvent(
                { distinct_id: '1234', event: 'my-event', uuid: 'asdf-zxcv' } as any,
                { config, logger, fetch: fetchMock } as any
            )

            expect(fetchMock.mock.calls[0][1]).toEqual({
                body: JSON.stringify([
                    {
                        distinct_id: '1234',
                        event: 'my-event',
                        uuid: 'asdf-zxcv',
                        token: 'test',
                    },
                ]),
                headers: {
                    'Content-Type': 'application/json',
                },
                method: 'POST',
            })
        })

        it('should correctly reverse the autocapture format', async () => {
            await onEvent(mockAutocaptureEvent, { config, logger, fetch: fetchMock } as any)
            expect(fetchMock.mock.calls[0][1]).toEqual({
                body: JSON.stringify([
                    {
                        distinct_id: '12345',
                        event: '$autocapture',
                        timestamp: '2022-12-06T12:54:30.810Z',
                        uuid: '0184e780-8f2b-0000-9e00-4cdcba315fe9',
                        token: 'test',
                        properties: {
                            $ip: '127.0.0.1',
                            $os: 'Mac OS X',
                            $browser: 'Firefox',
                            $elements: [
                                {
                                    order: 0,
                                    tag_name: 'div',
                                    attr_class: 'view-line',
                                    nth_child: 18,
                                    nth_of_type: 18,
                                    attr__class: 'view-line',
                                    attr__style: 'top:396px;height:18px;',
                                },
                                {
                                    order: 1,
                                    tag_name: 'div',
                                    attr_class: 'view-lines monaco-mouse-cursor-text',
                                    nth_child: 4,
                                    nth_of_type: 4,
                                    'attr__aria-hidden': 'true',
                                    attr__class: 'view-lines monaco-mouse-cursor-text',
                                    'attr__data-mprt': '7',
                                    attr__role: 'presentation',
                                    attr__style:
                                        'position: absolute; font-family: Menlo, Monaco, \\"Courier New\\", monospace; font-weight: normal; font-size: 12px; font-feature-settings: \\"liga\\" 0, \\"calt\\" 0; line-height: 18px; letter-spacing: 0px; width: 899px; height: 1438px;',
                                },
                                {
                                    order: 2,
                                    tag_name: 'div',
                                    attr_class: 'lines-content monaco-editor-background',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class: 'lines-content monaco-editor-background',
                                    attr__style:
                                        'position: absolute; overflow: hidden; width: 1000000px; height: 1000000px; transform: translate3d(0px, 0px, 0px); contain: strict; top: -93px; left: 0px;',
                                },
                                {
                                    order: 3,
                                    tag_name: 'div',
                                    attr_class: 'monaco-scrollable-element editor-scrollable vs-dark mac',
                                    nth_child: 2,
                                    nth_of_type: 2,
                                    attr__class: 'monaco-scrollable-element editor-scrollable vs-dark mac',
                                    'attr__data-mprt': '5',
                                    attr__role: 'presentation',
                                    attr__style:
                                        'position: absolute; overflow: hidden; left: 62px; width: 899px; height: 700px;',
                                },
                                {
                                    order: 4,
                                    tag_name: 'div',
                                    attr_class: 'overflow-guard',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class: 'overflow-guard',
                                    'attr__data-mprt': '3',
                                    attr__style: 'width: 961px; height: 700px;',
                                },
                                {
                                    order: 5,
                                    tag_name: 'div',
                                    attr_class:
                                        'monaco-editor no-user-select mac  showUnused showDeprecated vs-dark focused',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class:
                                        'monaco-editor no-user-select mac  showUnused showDeprecated vs-dark focused',
                                    'attr__data-uri': 'file:///index.ts',
                                    attr__role: 'code',
                                    attr__style: 'width: 961px; height: 700px;',
                                },
                                {
                                    order: 6,
                                    tag_name: 'div',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    'attr__data-keybinding-context': '2',
                                    'attr__data-mode-id': 'typescript',
                                    attr__style: 'width: 100%;',
                                },
                                {
                                    order: 7,
                                    tag_name: 'section',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__style:
                                        'display: flex; position: relative; text-align: initial; width: 100%; height: 700px;',
                                },
                                {
                                    order: 8,
                                    tag_name: 'div',
                                    attr_class: 'Field flex gap-2 flex-col',
                                    nth_child: 3,
                                    nth_of_type: 2,
                                    attr__class: 'Field flex gap-2 flex-col',
                                },
                                {
                                    order: 9,
                                    tag_name: 'form',
                                    attr_class: 'PluginSource',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class: 'PluginSource',
                                },
                                {
                                    order: 10,
                                    tag_name: 'div',
                                    attr_class: 'ant-drawer-body',
                                    nth_child: 2,
                                    nth_of_type: 2,
                                    attr__class: 'ant-drawer-body',
                                },
                                {
                                    order: 11,
                                    tag_name: 'div',
                                    attr_class: 'ant-drawer-wrapper-body',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class: 'ant-drawer-wrapper-body',
                                },
                                {
                                    order: 12,
                                    tag_name: 'div',
                                    attr_class: 'ant-drawer-content',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class: 'ant-drawer-content',
                                },
                                {
                                    order: 13,
                                    tag_name: 'div',
                                    attr_class: 'ant-drawer-content-wrapper',
                                    nth_child: 2,
                                    nth_of_type: 2,
                                    attr__class: 'ant-drawer-content-wrapper',
                                    attr__style: 'width: min(90vw, 64rem);',
                                },
                                {
                                    order: 14,
                                    tag_name: 'div',
                                    attr_class: 'ant-drawer ant-drawer-left ant-drawer-open',
                                    nth_child: 1,
                                    nth_of_type: 1,
                                    attr__class: 'ant-drawer ant-drawer-left ant-drawer-open',
                                    attr__style: 'z-index: 950;',
                                    attr__tabindex: '-1',
                                },
                                { order: 15, tag_name: 'div', nth_child: 12, nth_of_type: 7 },
                                {
                                    order: 16,
                                    tag_name: 'body',
                                    attr_class: 'ant-scrolling-effect',
                                    nth_child: 7,
                                    nth_of_type: 1,
                                    attr__class: 'ant-scrolling-effect',
                                    attr__style: 'touch-action: none; width: calc(100% - 15px); overflow: hidden;',
                                },
                            ],
                        },
                    },
                ]),
                headers: {
                    'Content-Type': 'application/json',
                },
                method: 'POST',
            })
        })
    })

    describe('error management', () => {
        it('succeeds and logs on 200', async () => {
            mockResponse({}, 200)
            await onEvent(mockEvent, {
                config,
                fetch: fetchMock,
                logger,
            } as any)
            expect(logger.log).toHaveBeenCalledWith('Flushed 1 event to localhost:8000')
        })

        it('skips and warns without throwing on 400s', async () => {
            mockResponse({}, 400)
            await onEvent(mockEvent, {
                config,
                fetch: fetchMock,
                logger,
            } as any)
            expect(logger.warn).toHaveBeenCalledWith('Skipping 1 event, rejected by localhost:8000: 400')
        })

        it('throws RetryError on 500s', async () => {
            mockResponse({}, 500)
            await expect(
                onEvent(mockEvent, {
                    config,
                    fetch: fetchMock,
                    logger,
                } as any)
            ).rejects.toThrow(RetryError)
            expect(logger.error).toHaveBeenCalledWith(
                'Failed to submit 1 event to localhost:8000 due to server error: 500'
            )
        })
    })
})
