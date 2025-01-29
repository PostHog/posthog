import { customerioPlugin } from './customerio'
import { hubspotPlugin } from './hubspot'
import { intercomPlugin } from './intercom'
import { rudderstackPlugin } from './rudderstack-posthog'
import { engagePlugin } from './posthog-engage-so'
import { avoPlugin } from './posthog-avo'
import { patternsPlugin } from './posthog-patterns-app'
import { brazePlugin } from './posthog-braze-app'
import { pubsubPlugin } from './pubsub'
import { sendgridPlugin } from './sendgrid'
import { gcsPlugin } from './posthog-gcs'
import { salesforcePlugin } from './salesforce/src'
import { laudspeakerPlugin } from './posthog-laudspeaker-app'

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
