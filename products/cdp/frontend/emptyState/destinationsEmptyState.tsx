import * as trafficControllerPng from '@posthog/brand/hoggies/png/traffic-controller'
import { IconSend } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { DestinationsPreview } from './DestinationsPreview'
import { destinationsSetupLogic } from './destinationsSetupLogic'

const HedgehogTrafficController = pngHoggie(trafficControllerPng)

export const destinationsEmptyState: SceneProductEmptyState = {
    statusLogic: destinationsSetupLogic,
    config: {
        productKey: ProductKey.PIPELINE_DESTINATIONS,
        productName: 'Destinations',
        icon: <IconSend />,
        accentColor: 'var(--color-product-data-pipeline-light)',
        accentColorDark: 'var(--color-product-data-pipeline-dark)',
        hedgehog: HedgehogTrafficController,
        text: {
            'needs-setup': {
                headline: 'Send your events where your team already works',
                lead: 'A destination forwards events from PostHog to another tool as they arrive, or in scheduled batches to a warehouse. Start from a template for Slack, webhooks, Salesforce, BigQuery, S3, and dozens more, filter which events it gets, and watch every delivery and failure from one list.',
            },
        },
        primaryAction: {
            label: 'Create your first destination',
            to: urls.dataPipelinesNew('destination'),
            dataAttr: 'new-destination',
        },
        docsUrl: 'https://posthog.com/docs/cdp/destinations',
        previewLabel: 'Your destinations, once connected',
        Preview: DestinationsPreview,
    },
}
