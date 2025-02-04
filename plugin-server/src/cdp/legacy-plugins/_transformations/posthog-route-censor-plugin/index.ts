import { LegacyTransformationPlugin, LegacyTransformationPluginMeta } from '../../types'
import { processEvent } from './dist'
import metadata from './plugin.json'

// NOTE: The dist.js is a compiled version of the plugin as it is has external dependencies that it inlines
// It is mostly untouched other than removing console logs and moving the setup code here

const setupPlugin = ({ global, config, logger }: LegacyTransformationPluginMeta) => {
    global.properties = config.properties.split(',')
    global.setProperties = config.set_properties.split(',')
    global.setOnceProperties = config.set_once_properties.split(',')
    global.routes = typeof config.routes === 'string' ? JSON.parse(config.routes) : config.routes
    logger.debug('Plugin set up with global config: ', JSON.stringify(global, null, 2))
}

export const posthogRouteCensorPlugin: LegacyTransformationPlugin = {
    id: 'posthog-route-censor-plugin',
    metadata,
    processEvent,
    setupPlugin,
}
