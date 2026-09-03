import * as chart from '@posthog/brand/hoggies/png/chart'
import * as cursor from '@posthog/brand/hoggies/png/cursor'
import * as director from '@posthog/brand/hoggies/png/director'
import * as experiment from '@posthog/brand/hoggies/png/experiment'
import * as judge from '@posthog/brand/hoggies/png/judge'
import * as megaphone from '@posthog/brand/hoggies/png/megaphone'
import * as noir from '@posthog/brand/hoggies/png/noir-1'
import * as officeWorker from '@posthog/brand/hoggies/png/office-worker'
import * as panic from '@posthog/brand/hoggies/png/panic'
import * as phoneCall from '@posthog/brand/hoggies/png/phone-call'
import * as research from '@posthog/brand/hoggies/png/research'
import * as robot from '@posthog/brand/hoggies/png/robot'
import * as trafficController from '@posthog/brand/hoggies/png/traffic-controller'
import * as wizard from '@posthog/brand/hoggies/png/wizard-1'
import * as workflows from '@posthog/brand/hoggies/png/workflows'

import { pngHoggie } from 'lib/brand/hoggies'

import { ProductKey } from '~/queries/schema/schema-general'

import type { ProductPushDisplay } from './navPanelAdShared'

const HedgehogChart = pngHoggie(chart)
const HedgehogCursor = pngHoggie(cursor)
const HedgehogDirector = pngHoggie(director)
const HedgehogExperiment = pngHoggie(experiment)
const HedgehogJudge = pngHoggie(judge)
const HedgehogMegaphone = pngHoggie(megaphone)
const HedgehogNoir = pngHoggie(noir)
const HedgehogOfficeWorker = pngHoggie(officeWorker)
const HedgehogPanic = pngHoggie(panic)
const HedgehogPhoneCall = pngHoggie(phoneCall)
const HedgehogResearch = pngHoggie(research)
const HedgehogRobot = pngHoggie(robot)
const HedgehogTrafficController = pngHoggie(trafficController)
const HedgehogWizard = pngHoggie(wizard)
const HedgehogWorkflows = pngHoggie(workflows)

export const DEFAULT_PRODUCT_PUSH_DISPLAY: ProductPushDisplay = {
    Hoggie: HedgehogMegaphone,
    accentColor: 'var(--color-accent)',
    tagline:
        "We think your organization would get a lot out of this product - it works with the data you're already sending. Give it a try!",
}

// One entry per pushable product (see BLESSED_PRODUCT_ORDER / FALLBACK_PRODUCT_ORDER in
// products/growth/backend/product_push/selection.py). Products missing here fall back to
// DEFAULT_PRODUCT_PUSH_DISPLAY, so TAM-scheduled pushes of unlisted products still render.
export const PRODUCT_PUSH_DISPLAY: Partial<Record<ProductKey, ProductPushDisplay>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        Hoggie: HedgehogChart,
        accentColor: 'var(--color-product-product-analytics-light)',
        tagline:
            'Insights, funnels, trends, and retention - understand exactly what users do in your product, with the events you already send.',
        hoggieOffset: { x: 42 },
    },
    [ProductKey.WEB_ANALYTICS]: {
        Hoggie: HedgehogCursor,
        accentColor: 'var(--color-product-web-analytics-light)',
        tagline:
            'Visitors, pageviews, and conversions on one simple dashboard. Like GA, without the pain - and no extra setup, ready for you to use.',
        hoggieOffset: { x: 72, y: 12 },
    },
    [ProductKey.SESSION_REPLAY]: {
        Hoggie: HedgehogDirector,
        accentColor: 'var(--color-product-session-replay-light)',
        tagline:
            'Lights, camera, action - watch real users move through your product and see exactly where they get stuck.',
        hoggieOffset: { x: 65, y: 32 },
    },
    [ProductKey.ERROR_TRACKING]: {
        Hoggie: HedgehogPanic,
        accentColor: 'var(--color-product-error-tracking-light)',
        tagline:
            'Catch exceptions before your users tweet about them - errors grouped, triaged, and linked to the sessions that hit them.',
        hoggieOffset: { x: 30 },
    },
    [ProductKey.FEATURE_FLAGS]: {
        Hoggie: HedgehogTrafficController,
        accentColor: 'var(--color-product-feature-flags-light)',
        tagline: 'Ship to 1% before you ship to everyone. Roll out, target, and roll back - no redeploys needed.',
        hoggieOffset: { x: 72 },
    },
    [ProductKey.EXPERIMENTS]: {
        Hoggie: HedgehogExperiment,
        accentColor: 'var(--color-product-experiments-light)',
        tagline: 'Stop debating, start testing. Run A/B tests on real users and let the data settle the argument.',
        hoggieOffset: { x: 62 },
    },
    [ProductKey.CONVERSATIONS]: {
        Hoggie: HedgehogPhoneCall,
        accentColor: 'var(--color-product-support-light)',
        tagline:
            'Talk to users right inside your product, with their session and event history next to every conversation.',
        hoggieOffset: { x: 77 },
    },
    [ProductKey.DATA_WAREHOUSE]: {
        Hoggie: HedgehogOfficeWorker,
        accentColor: 'var(--color-product-data-warehouse-light)',
        tagline:
            'Query everything with SQL - your product events plus warehouse sources like Stripe, HubSpot, and Postgres.',
        hoggieOffset: { x: 65, y: 6 },
    },
    [ProductKey.AI_OBSERVABILITY]: {
        Hoggie: HedgehogRobot,
        accentColor: 'var(--color-product-llm-analytics-light)',
        tagline:
            "Traces, costs, and latency for every LLM call - know what your AI is doing, and what it's costing you.",
        hoggieOffset: { x: 54 },
    },
    [ProductKey.LLM_CLUSTERS]: {
        Hoggie: HedgehogResearch,
        accentColor: 'var(--color-product-llm-clusters-light)',
        tagline: 'Thousands of AI conversations, automatically grouped into patterns you can actually act on.',
        hoggieOffset: { x: 20 },
    },
    [ProductKey.LLM_EVALUATIONS]: {
        Hoggie: HedgehogJudge,
        accentColor: 'var(--color-product-llm-evaluations-light)',
        tagline: 'Grade your LLM outputs at scale and catch regressions before your users do.',
        hoggieOffset: { x: 73 },
    },
    [ProductKey.LLM_PROMPTS]: {
        Hoggie: HedgehogWizard,
        accentColor: 'var(--color-product-llm-analytics-light)',
        tagline: 'Version, test, and ship prompt changes without redeploying your app. A little magic, fully tracked.',
        hoggieOffset: { x: 82 },
    },
    [ProductKey.LOGS]: {
        Hoggie: HedgehogNoir,
        accentColor: 'var(--color-product-logs-light)',
        tagline: 'Search every log line alongside your product data - no mystery goes unsolved.',
        hoggieOffset: { x: 75 },
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
