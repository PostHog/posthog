import { template as downsamplingPlugin } from '../legacy-plugins/_transformations/downsampling-plugin/template'
import { template as dropEventsOnPropertyPluginTemplate } from '../legacy-plugins/_transformations/drop-events-on-property-plugin/template'
import { template as flattenPropertiesPluginTemplate } from '../legacy-plugins/_transformations/flatten-properties-plugin/template'
import { template as languageUrlSplitterTemplate } from '../legacy-plugins/_transformations/language-url-splitter-app/template'
import { template as phShotgunProcessEventAppTemplate } from '../legacy-plugins/_transformations/ph-shotgun-processevent-app/template'
import { template as pluginAdvancedGeoipTemplate } from '../legacy-plugins/_transformations/plugin-advanced-geoip/template'
import { template as posthogNetdataEventProcessingPluginTemplate } from '../legacy-plugins/_transformations/plugin-netdata-event-processing/template'
import { template as pluginStonlyCleanCampaignNameTemplate } from '../legacy-plugins/_transformations/Plugin-Stonly-Clean-Campaign-Name/template'
import { template as pluginStonlyUtmExtractorTemplate } from '../legacy-plugins/_transformations/plugin-stonly-UTM-Extractor/template'
import { template as pluginPosthogAnonymizationTemplate } from '../legacy-plugins/_transformations/posthog-anonymization/template'
import { template as posthogAppUnduplicatorTemplate } from '../legacy-plugins/_transformations/posthog-app-unduplicator/template'
import { template as posthogAppUrlParametersToEventPropertiesTemplate } from '../legacy-plugins/_transformations/posthog-app-url-parameters-to-event-properties/template'
import { template as posthogFilterOutTemplate } from '../legacy-plugins/_transformations/posthog-filter-out-plugin/template'
import { template as posthogPluginGeoipTemplate } from '../legacy-plugins/_transformations/posthog-plugin-geoip/template'
import { template as posthogSnowplowRefererParserTemplate } from '../legacy-plugins/_transformations/posthog-plugin-snowplow-referer-parser/template'
import { template as posthogRouteCensorPluginTemplate } from '../legacy-plugins/_transformations/posthog-route-censor-plugin/template'
import { template as posthogUrlNormalizerTemplate } from '../legacy-plugins/_transformations/posthog-url-normalizer-plugin/template'
import { template as propertyFilterTemplate } from '../legacy-plugins/_transformations/property-filter-plugin/template'
import { template as semverFlattenerTemplate } from '../legacy-plugins/_transformations/semver-flattener-plugin/template'
import { template as taxonomyTemplate } from '../legacy-plugins/_transformations/taxonomy-plugin/template'
import { template as timestampParserTemplate } from '../legacy-plugins/_transformations/timestamp-parser-plugin/template'
import { template as userAgentTemplate } from '../legacy-plugins/_transformations/user-agent-plugin/template'
import { template as webhookTemplate } from './_destinations/webhook/webhook.template'
import { template as defaultTransformationTemplate } from './_transformations/default/default.template'
import { template as geoipTemplate } from './_transformations/geoip/geoip.template'
import { HogFunctionTemplate } from './types'

export const HOG_FUNCTION_TEMPLATES_DESTINATIONS: HogFunctionTemplate[] = [webhookTemplate]

export const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS: HogFunctionTemplate[] = [
    defaultTransformationTemplate,
    geoipTemplate,
    downsamplingPlugin,
    languageUrlSplitterTemplate,
    posthogAppUrlParametersToEventPropertiesTemplate,
    posthogFilterOutTemplate,
    posthogUrlNormalizerTemplate,
    propertyFilterTemplate,
    semverFlattenerTemplate,
    taxonomyTemplate,
    timestampParserTemplate,
    userAgentTemplate,
]

export const HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED: HogFunctionTemplate[] = [
    dropEventsOnPropertyPluginTemplate,
    flattenPropertiesPluginTemplate,
    phShotgunProcessEventAppTemplate,
    pluginAdvancedGeoipTemplate,
    posthogNetdataEventProcessingPluginTemplate,
    pluginStonlyCleanCampaignNameTemplate,
    pluginStonlyUtmExtractorTemplate,
    posthogAppUnduplicatorTemplate,
    posthogPluginGeoipTemplate,
    posthogSnowplowRefererParserTemplate,
    posthogRouteCensorPluginTemplate,
    pluginPosthogAnonymizationTemplate,
]

export const HOG_FUNCTION_TEMPLATES: HogFunctionTemplate[] = [
    ...HOG_FUNCTION_TEMPLATES_DESTINATIONS,
    ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS,
    ...HOG_FUNCTION_TEMPLATES_TRANSFORMATIONS_DEPRECATED,
]
