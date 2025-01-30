import { customerioPlugin } from './_destinations/customerio'
import { intercomPlugin } from './_destinations/intercom'
import { downsamplingPlugin } from './_transformations/downsampling-plugin'
import { languageUrlSplitterApp } from './_transformations/language-url-splitter-app'
import { posthogAppUrlParametersToEventPropertiesPlugin } from './_transformations/posthog-app-url-parameters-to-event-properties'
import { posthogFilterOutPlugin } from './_transformations/posthog-filter-out-plugin'
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

export const TRANSFORMATION_PLUGINS_BY_ID = {
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
