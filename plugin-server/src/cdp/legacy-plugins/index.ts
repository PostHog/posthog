import { customerioPlugin } from './_destinations/customerio/template'
import { hubspotPlugin } from './_destinations/hubspot/template'
import { downsamplingPlugin } from './_transformations/downsampling-plugin/template'
import { dropEventsOnPropertyPlugin } from './_transformations/drop-events-on-property-plugin/template'
import { flattenPropertiesPlugin } from './_transformations/flatten-properties-plugin/template'
import { languageUrlSplitterApp } from './_transformations/language-url-splitter-app/template'
import { phShotgunProcessEventApp } from './_transformations/ph-shotgun-processevent-app/template'
import { pluginAdvancedGeoip } from './_transformations/plugin-advanced-geoip/template'
import { pluginNetdataEventProcessing } from './_transformations/plugin-netdata-event-processing/template'
import { pluginStonlyCleanCampaignName } from './_transformations/Plugin-Stonly-Clean-Campaign-Name/template'
import { pluginStonlyUtmExtractor } from './_transformations/plugin-stonly-UTM-Extractor/template'
import { posthogAnonymization } from './_transformations/posthog-anonymization/template'
import { posthogAppUnduplicator } from './_transformations/posthog-app-unduplicator/template'
import { posthogAppUrlParametersToEventProperties } from './_transformations/posthog-app-url-parameters-to-event-properties/template'
import { posthogFilterOutPlugin } from './_transformations/posthog-filter-out-plugin/template'
import { posthogPluginGeoip } from './_transformations/posthog-plugin-geoip/template'
import { posthogPluginSnowplowRefererParser } from './_transformations/posthog-plugin-snowplow-referer-parser/template'
import { posthogRouteCensorPlugin } from './_transformations/posthog-route-censor-plugin/template'
import { posthogUrlNormalizerPlugin } from './_transformations/posthog-url-normalizer-plugin/template'
import { propertyFilterPlugin } from './_transformations/property-filter-plugin/template'
import { semverFlattenerPlugin } from './_transformations/semver-flattener-plugin/template'
import { taxonomyPlugin } from './_transformations/taxonomy-plugin/template'
import { timestampParserPlugin } from './_transformations/timestamp-parser-plugin/template'
import { userAgentPlugin } from './_transformations/user-agent-plugin/template'
import { LegacyDestinationPlugin, LegacyTransformationPlugin } from './types'

export const DESTINATION_PLUGINS: LegacyDestinationPlugin[] = [customerioPlugin, hubspotPlugin]
export const TRANSFORMATION_PLUGINS: LegacyTransformationPlugin[] = [
    downsamplingPlugin,
    dropEventsOnPropertyPlugin,
    flattenPropertiesPlugin,
    languageUrlSplitterApp,
    phShotgunProcessEventApp,
    pluginAdvancedGeoip,
    pluginNetdataEventProcessing,
    pluginStonlyCleanCampaignName,
    pluginStonlyUtmExtractor,
    posthogAnonymization,
    posthogAppUnduplicator,
    posthogAppUrlParametersToEventProperties,
    posthogFilterOutPlugin,
    posthogPluginGeoip,
    posthogPluginSnowplowRefererParser,
    posthogRouteCensorPlugin,
    posthogUrlNormalizerPlugin,
    propertyFilterPlugin,
    semverFlattenerPlugin,
    taxonomyPlugin,
    timestampParserPlugin,
    userAgentPlugin,
]

export const DESTINATION_PLUGINS_BY_ID = DESTINATION_PLUGINS.reduce((acc, plugin) => {
    acc[plugin.template.id] = plugin
    return acc
}, {} as Record<string, LegacyDestinationPlugin>)

export const TRANSFORMATION_PLUGINS_BY_ID = TRANSFORMATION_PLUGINS.reduce((acc, plugin) => {
    acc[plugin.template.id] = plugin
    return acc
}, {} as Record<string, LegacyTransformationPlugin>)
