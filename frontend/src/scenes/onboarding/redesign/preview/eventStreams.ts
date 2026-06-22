import { type PreviewEvent } from './types'

type Person = Pick<PreviewEvent, 'person' | 'initial' | 'color' | 'anon'>

/** Invented people for the activity feed — brandless domains plus a couple of anonymous ids; fixed order so snapshots don't drift. */
const PERSONS: Person[] = [
    { person: 'arjun@quillstack.com', initial: 'A', color: 'bg-[#29abc6]' },
    { person: 'maya@northwind.co', initial: 'M', color: 'bg-[#b62ad9]' },
    { person: '89b98457-323b-467b', initial: '8', color: 'bg-[#1d4aff]', anon: true },
    { person: 'emma@stackline.io', initial: 'E', color: 'bg-[#8567ff]' },
    { person: 'f3b8d92c-1e4a-9c7f', initial: 'F', color: 'bg-[#eb9d2a]', anon: true },
    { person: 'noah@feltboard.app', initial: 'N', color: 'bg-[#f54e00]' },
    { person: 'sofia@cedarworks.com', initial: 'S', color: 'bg-[#f35454]' },
    { person: 'liam@orbitgrid.com', initial: 'L', color: 'bg-[#6aa84f]' },
    { person: 'a7d2e5b1-44c8-0fa3', initial: 'A', color: 'bg-[#b62ad9]', anon: true },
    { person: 'mia@tideflow.io', initial: 'M', color: 'bg-[#1d4aff]' },
]

/** Believable, invented page URLs (not real prod) assigned to web events. */
const URLS = [
    'https://app.northwind.co/dashboard',
    'https://cedarworks.com/pricing',
    'https://lumenpath.dev/docs/getting-started',
    'https://app.tideflow.io/settings/billing',
    'https://orbitgrid.com/blog/launch?ref=hn',
    'https://quillstack.com/product/checkout',
]

interface EventDef {
    /** Display label (humanized for recognized PostHog events, as the app would show it). */
    label: string
    /** Recognized PostHog/core event — gets the colorful PostHog icon. */
    recognized?: boolean
    /** Carries a URL in the URL/SCREEN column. */
    url?: boolean
}

/** Recognized PostHog events that dominate a real stream — each shows the PostHog icon and a humanized label. */
const RECOGNIZED_EVENTS: EventDef[] = [
    { label: 'Pageview', recognized: true, url: true },
    { label: 'Exception', recognized: true, url: true },
    { label: 'Autocapture', recognized: true, url: true },
    { label: 'Pageview', recognized: true, url: true },
    { label: 'Feature flag called', recognized: true },
    { label: 'Pageleave', recognized: true, url: true },
    { label: 'Exception', recognized: true, url: true },
    { label: 'Autocapture', recognized: true, url: true },
    { label: 'Pageview', recognized: true, url: true },
    { label: 'Rageclick', recognized: true },
]

/** Archetype id (see data/archetypes.ts) → custom product events (shown as-is, no icon). */
const ARCHETYPE_PRODUCT_EVENTS: Record<string, string[]> = {
    b2b_saas: ['workspace_created', 'invite_sent', 'report_exported', 'subscription_upgraded', 'api_key_created'],
    consumer: ['profile_updated', 'content_shared', 'push_enabled', 'notification_opened', 'streak_extended'],
    ecommerce: ['product_viewed', 'add_to_cart', 'checkout_started', 'order_completed', 'coupon_applied'],
    ai_product: [
        'prompt_submitted',
        'generation_completed',
        'credits_purchased',
        'model_switched',
        'feedback_submitted',
    ],
    marketplace: ['listing_created', 'search_performed', 'message_sent', 'booking_confirmed', 'offer_made'],
    dev_tool: ['api_request', 'sdk_installed', 'error_captured', 'webhook_delivered', 'build_triggered'],
}

const DEFAULT_PRODUCT_EVENTS = ['sign_up', 'feature_used', 'button_clicked', 'form_submitted', 'subscription_started']

const DECK_SIZE = 18

/**
 * Builds a looping deck for the preview activity feed: mostly recognized PostHog events (~2:1) with the
 * archetype's custom product events sprinkled in. Deterministic (no randomness) so Storybook snapshots
 * stay stable; ActivityPage cycles through it on a timer.
 */
export function buildEventFeed(archetypeId: string | null | undefined): PreviewEvent[] {
    const products = (archetypeId && ARCHETYPE_PRODUCT_EVENTS[archetypeId]) || DEFAULT_PRODUCT_EVENTS
    const deck: PreviewEvent[] = []
    let recognizedCursor = 0
    let productCursor = 0
    let urlCursor = 0
    for (let i = 0; i < DECK_SIZE; i++) {
        // Every third event is a custom product event; the rest are recognized PostHog events.
        const def: EventDef =
            i % 3 === 2
                ? { label: products[productCursor++ % products.length] }
                : RECOGNIZED_EVENTS[recognizedCursor++ % RECOGNIZED_EVENTS.length]
        const person = PERSONS[(i * 3) % PERSONS.length]
        const url = def.url ? URLS[urlCursor++ % URLS.length] : undefined
        deck.push({ name: def.label, recognized: def.recognized, ...person, url })
    }
    return deck
}
