import { customerioPlugin } from './_destinations/customerio'
import { intercomPlugin } from './_destinations/intercom'
import { downsamplingPlugin } from './_transformations/downsampling-plugin'
import { dropEventsOnPropertyPlugin } from './_transformations/drop-events-on-property-plugin'
import { flattenPropertiesPlugin } from './_transformations/flatten-properties-plugin'
import { languageUrlSplitterApp } from './_transformations/language-url-splitter-app'
import { phShotgunProcessEventApp } from './_transformations/ph-shotgun-processevent-app'
import { pluginAdvancedGeoip } from './_transformations/plugin-advanced-geoip'
import { posthogNetdataEventProcessingPlugin } from './_transformations/plugin-netdata-event-processing'
import { pluginStonlyCleanCampaignName } from './_transformations/Plugin-Stonly-Clean-Campaign-Name'
import { pluginStonlyUtmExtractor } from './_transformations/plugin-stonly-UTM-Extractor'
import { pluginPosthogAnonymization } from './_transformations/posthog-anonymization'
import { posthogAppUnduplicator } from './_transformations/posthog-app-unduplicator'
import { posthogAppUrlParametersToEventPropertiesPlugin } from './_transformations/posthog-app-url-parameters-to-event-properties'
import { posthogFilterOutPlugin } from './_transformations/posthog-filter-out-plugin'
import { posthogPluginGeoip } from './_transformations/posthog-plugin-geoip'
import { posthogSnowplowRefererParser } from './_transformations/posthog-plugin-snowplow-referer-parser'
import { posthogRouteCensorPlugin } from './_transformations/posthog-route-censor-plugin'
import { posthogUrlNormalizerPlugin } from './_transformations/posthog-url-normalizer-plugin'
import { propertyFilterPlugin } from './_transformations/property-filter-plugin'
import { semverFlattenerPlugin } from './_transformations/semver-flattener-plugin'
import { taxonomyPlugin } from './_transformations/taxonomy-plugin'
import { timestampParserPlugin } from './_transformations/timestamp-parser-plugin'
import { userAgentPlugin } from './_transformations/user-agent-plugin'

export const DESTINATION_PLUGINS_BY_ID = {
    [customerioPlugin.id]: customerioPlugin,
    [intercomPlugin.id]: intercomPlugin,
}

export const DEPRECATED_TRANSFORMATION_PLUGINS_BY_ID = {
    [dropEventsOnPropertyPlugin.id]: dropEventsOnPropertyPlugin,
    [flattenPropertiesPlugin.id]: flattenPropertiesPlugin,
    [pluginAdvancedGeoip.id]: pluginAdvancedGeoip,
    [pluginStonlyCleanCampaignName.id]: pluginStonlyCleanCampaignName,
    [pluginStonlyUtmExtractor.id]: pluginStonlyUtmExtractor,
    [posthogAppUnduplicator.id]: posthogAppUnduplicator,
    [pluginPosthogAnonymization.id]: pluginPosthogAnonymization,
    [posthogPluginGeoip.id]: posthogPluginGeoip,
    [posthogRouteCensorPlugin.id]: posthogRouteCensorPlugin,
    [posthogNetdataEventProcessingPlugin.id]: posthogNetdataEventProcessingPlugin,
    [phShotgunProcessEventApp.id]: phShotgunProcessEventApp,
    [posthogSnowplowRefererParser.id]: posthogSnowplowRefererParser,
}

export const TRANSFORMATION_PLUGINS_BY_ID = {
    ...DEPRECATED_TRANSFORMATION_PLUGINS_BY_ID,
    [downsamplingPlugin.id]: downsamplingPlugin,
    [languageUrlSplitterApp.id]: languageUrlSplitterApp,
    [posthogAppUrlParametersToEventPropertiesPlugin.id]: posthogAppUrlParametersToEventPropertiesPlugin,
    [posthogFilterOutPlugin.id]: posthogFilterOutPlugin,
    [posthogUrlNormalizerPlugin.id]: posthogUrlNormalizerPlugin,
    [propertyFilterPlugin.id]: propertyFilterPlugin,
    [semverFlattenerPlugin.id]: semverFlattenerPlugin,
    [taxonomyPlugin.id]: taxonomyPlugin,
    [timestampParserPlugin.id]: timestampParserPlugin,
    [userAgentPlugin.id]: userAgentPlugin,
}
