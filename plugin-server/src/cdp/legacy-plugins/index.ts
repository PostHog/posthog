import { customerioPlugin } from './customerio'
import { hubspotPlugin } from './hubspot'
import { intercomPlugin } from './intercom'
import { avoPlugin } from './posthog-avo'
import { brazePlugin } from './posthog-braze-app'
import { engagePlugin } from './posthog-engage-so'
import { gcsPlugin } from './posthog-gcs'
import { laudspeakerPlugin } from './posthog-laudspeaker-app'
import { patternsPlugin } from './posthog-patterns-app'
import { pubsubPlugin } from './pubsub'
import { rudderstackPlugin } from './rudderstack-posthog'
import { salesforcePlugin } from './salesforce/src'
import { sendgridPlugin } from './sendgrid'

export const PLUGINS_BY_ID = {
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
}
