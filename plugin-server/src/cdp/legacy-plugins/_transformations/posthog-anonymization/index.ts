import { LegacyTransformationPlugin } from '../../types'
import { processEvent } from './src/processEvent'

export const pluginPosthogAnonymization: LegacyTransformationPlugin = {
    id: 'plugin-posthog-anonymization',
    processEvent,
}
