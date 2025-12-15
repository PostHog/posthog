import { PluginEvent } from '@posthog/plugin-scaffold'

import { internalEventHandlerRegistry } from '../internal-handlers'

export async function internalHandlersStep(event: PluginEvent): Promise<PluginEvent> {
    await internalEventHandlerRegistry.handleEvent(event)
    return event
}
