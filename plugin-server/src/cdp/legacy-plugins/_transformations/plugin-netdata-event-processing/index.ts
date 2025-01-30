import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from './dist'

export const posthogNetdataEventProcessingPlugin: LegacyTransformationPlugin = {
    id: 'posthog-plugin-netdata-event-processing-plugin',
    processEvent: processEvent as any,
}
