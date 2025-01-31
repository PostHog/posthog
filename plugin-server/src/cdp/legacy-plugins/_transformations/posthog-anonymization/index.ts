import { LegacyTransformationPlugin } from '../../types'
import metadata from './plugin.json'
import { processEvent } from './src/processEvent'

export const pluginPosthogAnonymization: LegacyTransformationPlugin = {
    id: 'plugin-posthog-anonymization',
    metadata,
    processEvent,
}
