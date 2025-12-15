import { PluginEvent } from '@posthog/plugin-scaffold'

import { Celery } from '../../../utils/db/celery'
import { logger } from '../../../utils/logger'

export interface InternalEventHandlerContext {
    celery?: Celery
}

export interface InternalEventHandler {
    name: string
    events: string[]
    handle(event: PluginEvent, context: InternalEventHandlerContext): Promise<void>
}

class InternalEventHandlerRegistry {
    private handlers: InternalEventHandler[] = []
    private eventToHandlers: Map<string, InternalEventHandler[]> = new Map()
    private celery?: Celery

    register(handler: InternalEventHandler): void {
        this.handlers.push(handler)

        for (const eventName of handler.events) {
            const existing = this.eventToHandlers.get(eventName) || []
            existing.push(handler)
            this.eventToHandlers.set(eventName, existing)
        }

        logger.info('📋', `Registered internal event handler: ${handler.name} for events: ${handler.events.join(', ')}`)
    }

    setCelery(celery: Celery): void {
        this.celery = celery
    }

    getHandlersForEvent(eventName: string): InternalEventHandler[] {
        return this.eventToHandlers.get(eventName) || []
    }

    async handleEvent(event: PluginEvent): Promise<void> {
        const handlers = this.getHandlersForEvent(event.event)
        const context: InternalEventHandlerContext = {
            celery: this.celery,
        }

        for (const handler of handlers) {
            try {
                await handler.handle(event, context)
            } catch (error) {
                logger.error('🔔', `Internal event handler ${handler.name} failed`, { error, event: event.event })
            }
        }
    }
}

export const internalEventHandlerRegistry = new InternalEventHandlerRegistry()
