import * as phoneCallPng from '@posthog/brand/hoggies/png/phone-call'
import { IconSupport } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { SupportSetupCard } from '../components/SupportSetupCard/SupportSetupCard'
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
                lead: 'Collect tickets from a chat widget, email, Slack, or your own contact form through the API into one inbox. Every ticket shows the person behind it, with their events, session replays, and past tickets alongside the conversation. Set SLAs, assign owners, and trigger workflows on ticket events.',
            },
            'waiting-for-data': {
                headline: 'Support is on. Waiting for your first ticket',
                lead: 'Tickets from every connected channel show up here as they arrive. Connect a channel below, then send it a test message to see a ticket land.',
            },
        },
        SetupCard: SupportSetupCard,
        docsUrl: 'https://posthog.com/docs/support',
        previewLabel: 'Your inbox, once tickets arrive',
        Preview: SupportPreview,
    },
}
