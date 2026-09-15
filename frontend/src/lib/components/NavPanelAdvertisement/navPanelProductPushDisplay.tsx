import * as chart from '@posthog/brand/hoggies/png/chart'
import * as codeBubble from '@posthog/brand/hoggies/png/code-bubble'
import * as cursor from '@posthog/brand/hoggies/png/cursor'
import * as deskWizard from '@posthog/brand/hoggies/png/desk-wizard'
import * as director from '@posthog/brand/hoggies/png/director'
import * as experiment from '@posthog/brand/hoggies/png/experiment'
import * as greek from '@posthog/brand/hoggies/png/greek'
import * as judge from '@posthog/brand/hoggies/png/judge'
import * as magnifyingGlass from '@posthog/brand/hoggies/png/magnifying-glass-1'
import * as megaphone from '@posthog/brand/hoggies/png/megaphone'
import * as organized from '@posthog/brand/hoggies/png/organized'
import * as panic from '@posthog/brand/hoggies/png/panic'
import * as phoneCall from '@posthog/brand/hoggies/png/phone-call'
import * as reading from '@posthog/brand/hoggies/png/reading'
import * as reporter from '@posthog/brand/hoggies/png/reporter'
import * as robot from '@posthog/brand/hoggies/png/robot'
import * as scientist from '@posthog/brand/hoggies/png/scientist'
import * as trafficController from '@posthog/brand/hoggies/png/traffic-controller'
import * as transformer from '@posthog/brand/hoggies/png/transformer'
import * as workflows from '@posthog/brand/hoggies/png/workflows'
import * as xRay from '@posthog/brand/hoggies/png/x-ray'
import { IconAI, IconGithub } from '@posthog/icons'

import { Logomark } from 'lib/brand'
import { pngHoggie } from 'lib/brand/hoggies'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import type { ProductPushDisplay } from './navPanelAdShared'

const HedgehogChart = pngHoggie(chart)
const HedgehogCodeBubble = pngHoggie(codeBubble)
const HedgehogCursor = pngHoggie(cursor)
const HedgehogDeskWizard = pngHoggie(deskWizard)
const HedgehogDirector = pngHoggie(director)
const HedgehogExperiment = pngHoggie(experiment)
const HedgehogGreek = pngHoggie(greek)
const HedgehogJudge = pngHoggie(judge)
const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlass)
const HedgehogMegaphone = pngHoggie(megaphone)
const HedgehogOrganized = pngHoggie(organized)
const HedgehogPanic = pngHoggie(panic)
const HedgehogPhoneCall = pngHoggie(phoneCall)
const HedgehogReading = pngHoggie(reading)
const HedgehogReporter = pngHoggie(reporter)
const HedgehogRobot = pngHoggie(robot)
const HedgehogScientist = pngHoggie(scientist)
const HedgehogTrafficController = pngHoggie(trafficController)
const HedgehogTransformer = pngHoggie(transformer)
const HedgehogWorkflows = pngHoggie(workflows)
const HedgehogXRay = pngHoggie(xRay)

export const DEFAULT_PRODUCT_PUSH_DISPLAY: ProductPushDisplay = {
    Hoggie: HedgehogMegaphone,
    accentColor: 'var(--color-accent)',
    tagline:
        "We think your organization would get a lot out of this product - it works with the data you're already sending. Give it a try!",
}

// Shared size for the icon-font surface logos (Slack, GitHub, Self-driving). Desktop's Logomark
// sizes itself via its own `size` prop instead.
const SURFACE_ICON_CLASS = 'text-[64px]'

// One entry per pushable product (see BLESSED_PRODUCT_ORDER / FALLBACK_PRODUCT_ORDER in
// products/growth/backend/product_push/selection.py). Products missing here fall back to
// DEFAULT_PRODUCT_PUSH_DISPLAY, so TAM-scheduled pushes of unlisted products still render.
// Each Hoggie matches the one in that product's own empty state, so the card and the screen it
// opens show the same hedgehog. Web analytics, error tracking and toolbar have none to follow.
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
        Hoggie: HedgehogOrganized,
        accentColor: 'var(--color-product-data-warehouse-light)',
        tagline:
            'Query everything with SQL - your product events plus warehouse sources like Stripe, HubSpot, and Postgres.',
        hoggieOffset: { x: 60, y: 18 },
    },
    [ProductKey.AI_OBSERVABILITY]: {
        Hoggie: HedgehogMagnifyingGlass,
        accentColor: 'var(--color-product-llm-analytics-light)',
        tagline:
            "Traces, costs, and latency for every LLM call - know what your AI is doing, and what it's costing you.",
        hoggieOffset: { x: 35, y: 18 },
    },
    [ProductKey.LLM_CLUSTERS]: {
        Hoggie: HedgehogScientist,
        accentColor: 'var(--color-product-llm-clusters-light)',
        tagline: 'Thousands of AI conversations, automatically grouped into patterns you can actually act on.',
        hoggieOffset: { x: 52, y: 14 },
    },
    [ProductKey.LLM_EVALUATIONS]: {
        Hoggie: HedgehogJudge,
        accentColor: 'var(--color-product-llm-evaluations-light)',
        tagline: 'Grade your LLM outputs at scale and catch regressions before your users do.',
        hoggieOffset: { x: 73 },
    },
    [ProductKey.LLM_PROMPTS]: {
        Hoggie: HedgehogDeskWizard,
        accentColor: 'var(--color-product-llm-analytics-light)',
        tagline: 'Version, test, and ship prompt changes without redeploying your app. A little magic, fully tracked.',
        hoggieOffset: { x: 55, y: 10 },
    },
    [ProductKey.LOGS]: {
        Hoggie: HedgehogGreek,
        accentColor: 'var(--color-product-logs-light)',
        tagline: 'Search every log line alongside your product data - no mystery goes unsolved.',
        hoggieOffset: { x: 42, y: 22 },
    },
    [ProductKey.SURVEYS]: {
        Hoggie: HedgehogReporter,
        accentColor: 'var(--color-product-surveys-light)',
        tagline:
            'Ask users what they think inside your product, and read the answers next to the sessions behind them.',
        hoggieOffset: { x: 72, y: 26 },
    },
    [ProductKey.REPLAY_VISION]: {
        Hoggie: HedgehogXRay,
        accentColor: 'var(--color-product-session-replay-light)',
        tagline: 'AI watches your recordings and turns what happens in them into data you can query.',
        hoggieOffset: { x: 45, y: 12 },
    },
    [ProductKey.NOTEBOOKS]: {
        Hoggie: HedgehogReading,
        accentColor: 'var(--color-product-notebooks-light)',
        tagline: 'Collect insights, replays, and notes on one page, so an investigation still reads well next month.',
        hoggieOffset: { x: 28, y: 20 },
    },
    [ProductKey.ENDPOINTS]: {
        Hoggie: HedgehogCodeBubble,
        accentColor: 'var(--color-product-endpoints-light)',
        tagline: 'Turn a saved query into an API your app can call, with caching and no infrastructure to run.',
        hoggieOffset: { x: 70, y: 16 },
    },
    [ProductKey.TOOLBAR]: {
        Hoggie: HedgehogTransformer,
        accentColor: 'var(--color-accent)',
        tagline: 'Click any element on your own site to see how it performs, then turn it into an action.',
        hoggieOffset: { x: 65, y: 20 },
    },
    [ProductKey.MCP_ANALYTICS]: {
        Hoggie: HedgehogRobot,
        accentColor: 'var(--color-product-mcp-analytics-light)',
        tagline: 'See which of your MCP tools agents reach for, how long each call takes, and where they fail.',
        hoggieOffset: { x: 54 },
    },
    [ProductKey.MARKETING_ANALYTICS]: {
        Hoggie: HedgehogMegaphone,
        accentColor: 'var(--color-product-marketing-analytics-light)',
        tagline: 'Track ad spend next to the signups it produced, so you can see which channels are worth the money.',
        hoggieOffset: { x: 70 },
    },
    [ProductKey.WORKFLOWS]: {
        Hoggie: HedgehogWorkflows,
        accentColor: 'var(--color-product-workflows-light)',
        tagline: 'Automate messages and actions triggered by what users actually do in your product.',
    },
    // Surfaces that aren't catalog products carry their own label, destination, and logo.
    [ProductKey.SELF_DRIVING]: {
        Icon: <IconAI className={`${SURFACE_ICON_CLASS} text-[color:var(--color-purple-300)]`} />,
        iconBackdrop: true,
        accentColor: 'var(--color-purple-300)',
        tagline:
            'Let PostHog watch your data and surface what needs attention - findings land in your inbox, ready to act on.',
        label: 'PostHog Self-driving',
        href: urls.inbox(),
    },
    [ProductKey.POSTHOG_SLACK]: {
        Icon: <IconSlack className={SURFACE_ICON_CLASS} />,
        accentColor: 'var(--color-accent)',
        tagline: 'Ask questions and get answers where your team already works. Add the PostHog app to Slack.',
        label: 'PostHog in Slack',
        href: urls.settings('environment-integrations', 'integration-slack'),
    },
    [ProductKey.POSTHOG_GITHUB]: {
        Icon: <IconGithub className={SURFACE_ICON_CLASS} />,
        accentColor: 'var(--color-text-primary)',
        tagline: 'Connect GitHub so PostHog in Slack and Self-driving can open pull requests, not just suggest fixes.',
        label: 'Connect GitHub',
        href: urls.settings('environment-integrations', 'integration-github'),
    },
    [ProductKey.POSTHOG_DESKTOP]: {
        Icon: <Logomark size="xl" />,
        iconUpright: true,
        accentColor: 'var(--color-accent)',
        tagline:
            'The product editor for builders. Run AI agents that use your product data as context to ship changes.',
        label: 'PostHog Desktop',
        href: 'https://posthog.com/desktop',
    },
}

export function getProductPushDisplay(productKey: string): ProductPushDisplay {
    return PRODUCT_PUSH_DISPLAY[productKey as ProductKey] ?? DEFAULT_PRODUCT_PUSH_DISPLAY
}
