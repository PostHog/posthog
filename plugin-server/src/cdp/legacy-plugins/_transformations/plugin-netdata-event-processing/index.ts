import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from './dist'
import metadata from './plugin.json'
export const posthogNetdataEventProcessingPlugin: LegacyTransformationPlugin = {
    id: 'posthog-plugin-netdata-event-processing-plugin',
    metadata,
    processEvent: processEvent as any,
}
