import { customerioPlugin } from './_destinations/customerio/template'
import { hubspotPlugin } from './_destinations/hubspot/template'
import { posthogFilterOutPlugin } from './_transformations/posthog-filter-out-plugin/template'
import { semverFlattenerPlugin } from './_transformations/semver-flattener-plugin/template'
import { LegacyDestinationPlugin, LegacyTransformationPlugin } from './types'

export const DESTINATION_PLUGINS: LegacyDestinationPlugin[] = [customerioPlugin, hubspotPlugin]
export const TRANSFORMATION_PLUGINS: LegacyTransformationPlugin[] = [semverFlattenerPlugin, posthogFilterOutPlugin]

export const DESTINATION_PLUGINS_BY_ID = DESTINATION_PLUGINS.reduce((acc, plugin) => {
    acc[plugin.template.id] = plugin
    return acc
}, {} as Record<string, LegacyDestinationPlugin>)

export const TRANSFORMATION_PLUGINS_BY_ID = TRANSFORMATION_PLUGINS.reduce((acc, plugin) => {
    acc[plugin.template.id] = plugin
    return acc
}, {} as Record<string, LegacyTransformationPlugin>)
