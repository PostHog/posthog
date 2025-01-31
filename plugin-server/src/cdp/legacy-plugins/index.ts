import { customerioPlugin } from './_destinations/customerio'
import { hubspotPlugin } from './_destinations/hubspot'
import { intercomPlugin } from './_destinations/intercom'
import { avoPlugin } from './_destinations/posthog-avo'
import { brazePlugin } from './_destinations/posthog-braze-app'
import { engagePlugin } from './_destinations/posthog-engage-so'
import { gcsPlugin } from './_destinations/posthog-gcs'
import { laudspeakerPlugin } from './_destinations/posthog-laudspeaker-app'
import { patternsPlugin } from './_destinations/posthog-patterns-app'
import { replicatorPlugin } from './_destinations/posthog-plugin-replicator'
import { pubsubPlugin } from './_destinations/pubsub'
import { rudderstackPlugin } from './_destinations/rudderstack-posthog'
import { salesforcePlugin } from './_destinations/salesforce'
import { sendgridPlugin } from './_destinations/sendgrid'
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
    [rudderstackPlugin.id]: rudderstackPlugin,
    [hubspotPlugin.id]: hubspotPlugin,
    [engagePlugin.id]: engagePlugin,
    [avoPlugin.id]: avoPlugin,
    [patternsPlugin.id]: patternsPlugin,
    [brazePlugin.id]: brazePlugin,
    [pubsubPlugin.id]: pubsubPlugin,
    [sendgridPlugin.id]: sendgridPlugin,
    [gcsPlugin.id]: gcsPlugin,
    [salesforcePlugin.id]: salesforcePlugin,
    [laudspeakerPlugin.id]: laudspeakerPlugin,
    [replicatorPlugin.id]: replicatorPlugin,
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
