import { PluginEvent } from '@posthog/plugin-scaffold'

import { InternalEventHandler, InternalEventHandlerContext, internalEventHandlerRegistry } from './registry'

const buildTestEvent = (eventName: string, overrides?: Partial<PluginEvent>): PluginEvent => ({
    event: eventName,
    distinct_id: 'user-123',
    team_id: 1,
    properties: {},
    ip: null,
    site_url: '',
    now: '',
    uuid: '',
    ...overrides,
})

describe('InternalEventHandlerRegistry', () => {
    beforeEach(() => {
        // Clear handlers between tests by accessing private field
        ;(internalEventHandlerRegistry as any).handlers = []
        ;(internalEventHandlerRegistry as any).eventToHandlers = new Map()
        ;(internalEventHandlerRegistry as any).celery = undefined
    })

    it('should register handlers and route events correctly', async () => {
        const handleMock = jest.fn()
        const handler: InternalEventHandler = {
            name: 'test-handler',
            events: ['test event'],
            handle: handleMock,
        }

        internalEventHandlerRegistry.register(handler)

        const event = buildTestEvent('test event')
        await internalEventHandlerRegistry.handleEvent(event)

        expect(handleMock).toHaveBeenCalledWith(event, expect.objectContaining<InternalEventHandlerContext>({}))
    })

    it('should not call handlers for non-matching events', async () => {
        const handleMock = jest.fn()
        const handler: InternalEventHandler = {
            name: 'test-handler',
            events: ['test event'],
            handle: handleMock,
        }

        internalEventHandlerRegistry.register(handler)

        const event = buildTestEvent('other event')
        await internalEventHandlerRegistry.handleEvent(event)

        expect(handleMock).not.toHaveBeenCalled()
    })

    it('should handle multiple handlers for same event', async () => {
        const handleMock1 = jest.fn()
        const handleMock2 = jest.fn()

        internalEventHandlerRegistry.register({
            name: 'handler-1',
            events: ['test event'],
            handle: handleMock1,
        })

        internalEventHandlerRegistry.register({
            name: 'handler-2',
            events: ['test event'],
            handle: handleMock2,
        })

        const event = buildTestEvent('test event')
        await internalEventHandlerRegistry.handleEvent(event)

        expect(handleMock1).toHaveBeenCalledWith(event, expect.any(Object))
        expect(handleMock2).toHaveBeenCalledWith(event, expect.any(Object))
    })

    it('should catch and log errors from handlers without failing', async () => {
        const errorHandler: InternalEventHandler = {
            name: 'error-handler',
            events: ['test event'],
            handle: jest.fn().mockRejectedValue(new Error('Handler error')),
        }

        internalEventHandlerRegistry.register(errorHandler)

        const event = buildTestEvent('test event')

        // Should not throw
        await expect(internalEventHandlerRegistry.handleEvent(event)).resolves.not.toThrow()
    })

    it('should support handlers for multiple events', async () => {
        const handleMock = jest.fn()
        const handler: InternalEventHandler = {
            name: 'multi-event-handler',
            events: ['event-a', 'event-b'],
            handle: handleMock,
        }

        internalEventHandlerRegistry.register(handler)

        await internalEventHandlerRegistry.handleEvent(buildTestEvent('event-a'))
        await internalEventHandlerRegistry.handleEvent(buildTestEvent('event-b'))

        expect(handleMock).toHaveBeenCalledTimes(2)
    })

    it('should pass celery in context when set', async () => {
        const handleMock = jest.fn()
        const mockCelery = { applyAsync: jest.fn() }

        internalEventHandlerRegistry.register({
            name: 'test-handler',
            events: ['test event'],
            handle: handleMock,
        })
        internalEventHandlerRegistry.setCelery(mockCelery as any)

        const event = buildTestEvent('test event')
        await internalEventHandlerRegistry.handleEvent(event)

        expect(handleMock).toHaveBeenCalledWith(event, { celery: mockCelery })
    })
})
