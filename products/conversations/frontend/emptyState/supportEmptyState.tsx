import * as phoneCallPng from '@posthog/brand/hoggies/png/phone-call'
import { IconSupport } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { SupportPreview } from './SupportPreview'
import { supportSetupLogic } from './supportSetupLogic'

const HedgehogPhoneCall = pngHoggie(phoneCallPng)

export const supportEmptyState: SceneProductEmptyState = {
    statusLogic: supportSetupLogic,
    config: {
        productKey: ProductKey.CONVERSATIONS,
        productName: 'Support',
        icon: <IconSupport />,
        accentColor: 'var(--color-product-support-light)',
        accentColorDark: 'var(--color-product-support-dark)',
        hedgehog: HedgehogPhoneCall,
        text: {
            'needs-setup': {
                headline: 'Answer support tickets with full product context',
                lead: 'Collect tickets from an in-app chat widget, email, or Slack into one inbox. Every ticket shows the person behind it, with their events, session replays, and past tickets alongside the conversation. Set SLAs, assign owners, and trigger workflows on ticket events.',
            },
            'waiting-for-data': {
                headline: 'Support is on. Waiting for your first ticket',
                lead: 'Tickets from your chat widget, email, and any other connected channels will show up here as they arrive. Send a test message through the widget to see one land, or finish connecting a channel in settings.',
            },
        },
        // `primaryAction` isn't keyed by mode the way `text` is, and support is the only
        // adopter with a middle state, so this copy has to read correctly both before
        // support is switched on and while it waits for a first ticket.
        primaryAction: { label: 'Open support settings', to: urls.supportSettings() },
        docsUrl: 'https://posthog.com/docs/support',
        previewLabel: 'Your inbox, once tickets arrive',
        Preview: SupportPreview,
    },
}
