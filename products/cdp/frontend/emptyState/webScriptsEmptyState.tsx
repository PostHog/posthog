import * as codeBubblePng from '@posthog/brand/hoggies/png/code-bubble'
import { IconPlug } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { WebScriptPreview } from './WebScriptPreview'
import { webScriptsSetupLogic } from './webScriptsSetupLogic'

const HedgehogCodeBubble = pngHoggie(codeBubblePng)

export const webScriptsEmptyState: SceneProductEmptyState = {
    statusLogic: webScriptsSetupLogic,
    config: {
        productKey: ProductKey.SITE_APPS,
        productName: 'Web scripts',
        icon: <IconPlug />,
        accentColor: 'var(--color-product-data-pipeline-light)',
        accentColorDark: 'var(--color-product-data-pipeline-dark)',
        hedgehog: HedgehogCodeBubble,
        text: {
            'needs-setup': {
                headline: 'Add scripts to your site without redeploying',
                lead: 'Web scripts run custom JavaScript on your site through the PostHog snippet you already have. Start from templates for banners, notifications, and chat-style widgets, or write your own. Enable, update, or disable each script from PostHog, with no code changes.',
            },
        },
        primaryAction: {
            label: 'Create your first web script',
            to: urls.webScriptsNew(),
            dataAttr: 'new-web-script',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/cdp',
        previewLabel: 'Your scripts, once created',
        Preview: WebScriptPreview,
    },
}
