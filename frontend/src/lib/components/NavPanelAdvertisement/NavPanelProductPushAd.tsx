import { BindLogic, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import {
    HedgehogChartHog,
    HedgehogCodeBubble,
    HedgehogCursorHog,
    HedgehogDirector,
    HedgehogExperiment,
    HedgehogJudge,
    HedgehogMegaphone,
    HedgehogNoirHog,
    HedgehogPanic,
    HedgehogPhoneCall,
    HedgehogPuzzle,
    HedgehogRoboHog,
    HedgehogTrafficController,
    HedgehogWizardHog,
    HedgehogWorkflows,
} from '@posthog/brand/hoggies'
import { Link } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { addProductIntent } from 'lib/utils/product-intents'

import { getTreeItemsProducts } from '~/products'
import { FileSystemImport, ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type { ProductPushCampaignApi } from 'products/growth/frontend/generated/api.schemas'

import { AdvertisementCard, ProductPushDisplay } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

export const DEFAULT_PRODUCT_PUSH_DISPLAY: ProductPushDisplay = {
    Hoggie: HedgehogMegaphone,
    accentColor: 'var(--color-accent)',
    tagline:
        "We think your organization would get a lot out of this product — it works with the data you're already sending. Give it a try!",
}

// One entry per pushable product (see BLESSED_PRODUCT_ORDER / FALLBACK_PRODUCT_ORDER in
// products/growth/backend/product_push/selection.py). Products missing here fall back to
// DEFAULT_PRODUCT_PUSH_DISPLAY, so TAM-scheduled pushes of unlisted products still render.
export const PRODUCT_PUSH_DISPLAY: Partial<Record<ProductKey, ProductPushDisplay>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        Hoggie: HedgehogChartHog,
        accentColor: 'var(--color-product-product-analytics-light)',
        tagline:
            'Funnels, trends, and retention — understand exactly what users do in your product, with the events you already send.',
    },
    [ProductKey.WEB_ANALYTICS]: {
        Hoggie: HedgehogCursorHog,
        accentColor: 'var(--color-product-web-analytics-light)',
        tagline:
            'Visitors, pageviews, and conversions on one simple dashboard. Like GA, without the pain — and no extra setup.',
    },
    [ProductKey.SESSION_REPLAY]: {
        Hoggie: HedgehogDirector,
        accentColor: 'var(--color-product-session-replay-light)',
        tagline:
            'Lights, camera, action — watch real users move through your product and see exactly where they get stuck.',
    },
    [ProductKey.ERROR_TRACKING]: {
        Hoggie: HedgehogPanic,
        accentColor: 'var(--color-product-error-tracking-light)',
        tagline:
            'Catch exceptions before your users tweet about them — errors grouped, triaged, and linked to the sessions that hit them.',
    },
    [ProductKey.FEATURE_FLAGS]: {
        Hoggie: HedgehogTrafficController,
        accentColor: 'var(--color-product-feature-flags-light)',
        tagline: 'Ship to 1% before you ship to everyone. Roll out, target, and roll back — no redeploys needed.',
    },
    [ProductKey.EXPERIMENTS]: {
        Hoggie: HedgehogExperiment,
        accentColor: 'var(--color-product-experiments-light)',
        tagline: 'Stop debating, start testing. Run A/B tests on real users and let the data settle the argument.',
    },
    [ProductKey.CONVERSATIONS]: {
        Hoggie: HedgehogPhoneCall,
        accentColor: 'var(--color-product-support-light)',
        tagline:
            'Talk to users right inside your product, with their session and event history next to every conversation.',
    },
    [ProductKey.DATA_WAREHOUSE]: {
        Hoggie: HedgehogCodeBubble,
        accentColor: 'var(--color-product-data-warehouse-light)',
        tagline:
            'Query everything with SQL — your product events plus warehouse sources like Stripe, HubSpot, and Postgres.',
    },
    // AI_OBSERVABILITY is the frontend enum name for the 'llm_analytics' product key
    [ProductKey.AI_OBSERVABILITY]: {
        Hoggie: HedgehogRoboHog,
        accentColor: 'var(--color-product-llm-analytics-light)',
        tagline:
            "Traces, costs, and latency for every LLM call — know what your AI is doing, and what it's costing you.",
    },
    [ProductKey.LLM_CLUSTERS]: {
        Hoggie: HedgehogPuzzle,
        accentColor: 'var(--color-product-llm-clusters-light)',
        tagline: 'Thousands of AI conversations, automatically grouped into patterns you can actually act on.',
    },
    [ProductKey.LLM_EVALUATIONS]: {
        Hoggie: HedgehogJudge,
        accentColor: 'var(--color-product-llm-evaluations-light)',
        tagline: 'Grade your LLM outputs at scale and catch regressions before your users do.',
    },
    [ProductKey.LLM_PROMPTS]: {
        Hoggie: HedgehogWizardHog,
        accentColor: 'var(--color-product-llm-prompts-light)',
        tagline: 'Version, test, and ship prompt changes without redeploying your app. A little magic, fully tracked.',
    },
    [ProductKey.LOGS]: {
        Hoggie: HedgehogNoirHog,
        accentColor: 'var(--color-product-logs-light)',
        tagline: 'Search every log line alongside your product data — no mystery goes unsolved.',
    },
    [ProductKey.WORKFLOWS]: {
        Hoggie: HedgehogWorkflows,
        accentColor: 'var(--color-product-workflows-light)',
        tagline: 'Automate messages and actions triggered by what users actually do in your product.',
    },
}

export function getProductPushDisplay(productKey: string): ProductPushDisplay {
    return PRODUCT_PUSH_DISPLAY[productKey as ProductKey] ?? DEFAULT_PRODUCT_PUSH_DISPLAY
}

export function NavPanelProductPushAd({ campaign }: { campaign: ProductPushCampaignApi }): JSX.Element | null {
    const allProducts = getTreeItemsProducts()
    const productInfo: FileSystemImport | undefined = allProducts.find(
        (p: FileSystemImport) => p.path === campaign.product_path
    )

    const logicProps = { campaign: `product-push-${campaign.id}` }
    const logic = navPanelAdvertisementLogic(logicProps)
    const { hidden } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const display = getProductPushDisplay(campaign.product_key)

    // Never advertise a product this user can't open (mirrors the sidebar's flag filtering)
    const flagGated = !!productInfo?.flag && !(featureFlags as Record<string, boolean>)[productInfo.flag]

    useEffect(() => {
        if (!hidden && productInfo && !flagGated) {
            posthog.capture('nav panel product push shown', {
                campaign_id: campaign.id,
                product_key: campaign.product_key,
            })
        }
    }, [campaign.id, campaign.product_key, productInfo, hidden, flagGated])

    if (hidden || !productInfo || flagGated) {
        return null
    }

    return (
        <div className="w-full">
            <Link
                to={productInfo.href}
                className="text-primary"
                onClick={() => {
                    posthog.capture('nav panel product push clicked', {
                        campaign_id: campaign.id,
                        product_key: campaign.product_key,
                    })
                    if (Object.values(ProductKey).includes(campaign.product_key as ProductKey)) {
                        addProductIntent({
                            product_type: campaign.product_key as ProductKey,
                            intent_context: ProductIntentContext.NAV_PANEL_ADVERTISEMENT_CLICKED,
                            metadata: { campaign_id: campaign.id },
                        })
                    }
                }}
            >
                <BindLogic logic={navPanelAdvertisementLogic} props={logicProps}>
                    <AdvertisementCard
                        title={productInfo.displayLabel ?? productInfo.path}
                        text={campaign.reason_text || display.tagline}
                        hero={display}
                        onClose={() => {
                            posthog.capture('nav panel product push dismissed', {
                                campaign_id: campaign.id,
                                product_key: campaign.product_key,
                            })
                        }}
                    />
                </BindLogic>
            </Link>
        </div>
    )
}
