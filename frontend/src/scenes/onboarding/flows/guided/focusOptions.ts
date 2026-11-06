import { ProductKey } from '~/queries/schema/schema-general'

export type Platform = 'web' | 'mobile' | 'server'
export type Industry =
    | 'ecommerce'
    | 'saas'
    | 'ai'
    | 'fintech'
    | 'health'
    | 'education'
    | 'media'
    | 'marketplace'
    | 'social'
    | 'gaming'
    | 'devtools'
    | 'travel'
    | 'other'
export type FocusArea = 'behavior' | 'health'

export interface FocusOption {
    key: string
    area: FocusArea
    label: string
    /** Completes "Reduce churn by 12%" style goals. */
    goalVerb: 'Increase' | 'Reduce'
    metric: string
    defaultTarget: number
    /** Events the install step asks the agent to track, so the goal is measurable on day one. */
    events: string[]
    products: ProductKey[]
    /** Industries that see this option. Omitted means every industry. */
    industries?: Industry[]
    /** Typed by the user: `metric` holds their words, and there is no target. */
    custom?: boolean
}

export const CUSTOM_FOCUS_KEY = 'custom'

export function customFocusOption(text: string): FocusOption {
    return {
        key: CUSTOM_FOCUS_KEY,
        area: 'behavior',
        label: text,
        goalVerb: 'Increase',
        metric: text,
        defaultTarget: 0,
        events: [],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        custom: true,
    }
}

export const FOCUS_OPTIONS: FocusOption[] = [
    {
        key: 'onboarding_conversion',
        area: 'behavior',
        label: 'Onboarding conversion',
        goalVerb: 'Increase',
        metric: 'onboarding conversion',
        defaultTarget: 15,
        events: ['signed up', 'onboarding completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
    },
    {
        key: 'retention',
        area: 'behavior',
        label: 'Week 1 retention',
        goalVerb: 'Increase',
        metric: 'week 1 retention',
        defaultTarget: 10,
        events: ['signed up', 'key action performed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
    },
    {
        key: 'churn',
        area: 'behavior',
        label: 'Churn',
        goalVerb: 'Reduce',
        metric: 'churn',
        defaultTarget: 10,
        events: ['subscription started', 'subscription canceled'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
    },
    {
        key: 'feature_adoption',
        area: 'behavior',
        label: 'Feature adoption',
        goalVerb: 'Increase',
        metric: 'adoption of a key feature',
        defaultTarget: 20,
        events: ['feature used'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS],
    },
    {
        key: 'free_to_paid',
        area: 'behavior',
        label: 'Free to paid conversion',
        goalVerb: 'Increase',
        metric: 'free to paid conversion',
        defaultTarget: 10,
        events: ['plan upgraded'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
    },
    {
        key: 'signup_conversion',
        area: 'behavior',
        label: 'Visitor to sign-up',
        goalVerb: 'Increase',
        metric: 'visitor to sign-up conversion',
        defaultTarget: 15,
        events: ['$pageview', 'signed up'],
        products: [ProductKey.WEB_ANALYTICS, ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
    },
    {
        key: 'errors',
        area: 'health',
        label: 'Errors users hit',
        goalVerb: 'Reduce',
        metric: 'users affected by errors',
        defaultTarget: 25,
        events: ['$exception'],
        products: [ProductKey.ERROR_TRACKING, ProductKey.SESSION_REPLAY],
    },
    {
        key: 'logs',
        area: 'health',
        label: 'Time to debug issues',
        goalVerb: 'Reduce',
        metric: 'time to debug issues',
        defaultTarget: 30,
        events: [],
        products: [ProductKey.LOGS, ProductKey.ERROR_TRACKING],
    },
    {
        key: 'page_speed',
        area: 'health',
        label: 'Page load time',
        goalVerb: 'Reduce',
        metric: 'page load time',
        defaultTarget: 20,
        events: [],
        products: [ProductKey.WEB_ANALYTICS, ProductKey.SESSION_REPLAY],
    },
    {
        key: 'safe_releases',
        area: 'health',
        label: 'Issues from releases',
        goalVerb: 'Reduce',
        metric: 'issues caused by releases',
        defaultTarget: 30,
        events: ['$exception'],
        products: [ProductKey.FEATURE_FLAGS, ProductKey.ERROR_TRACKING],
    },
    {
        key: 'checkout_conversion',
        area: 'behavior',
        label: 'Checkout conversion',
        goalVerb: 'Increase',
        metric: 'checkout conversion',
        defaultTarget: 10,
        events: ['product added to cart', 'checkout started', 'purchase completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['ecommerce'],
    },
    {
        key: 'cart_abandonment',
        area: 'behavior',
        label: 'Cart abandonment',
        goalVerb: 'Reduce',
        metric: 'cart abandonment',
        defaultTarget: 15,
        events: ['product added to cart', 'purchase completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.SURVEYS],
        industries: ['ecommerce'],
    },
    {
        key: 'repeat_purchase',
        area: 'behavior',
        label: 'Repeat purchases',
        goalVerb: 'Increase',
        metric: 'repeat purchase rate',
        defaultTarget: 10,
        events: ['purchase completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
        industries: ['ecommerce'],
    },
    {
        key: 'trial_to_paid',
        area: 'behavior',
        label: 'Trial to paid conversion',
        goalVerb: 'Increase',
        metric: 'trial to paid conversion',
        defaultTarget: 10,
        events: ['trial started', 'plan upgraded'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['saas'],
    },
    {
        key: 'team_invites',
        area: 'behavior',
        label: 'Team invites',
        goalVerb: 'Increase',
        metric: 'accounts that invite a teammate',
        defaultTarget: 20,
        events: ['invite sent', 'invite accepted'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
        industries: ['saas'],
    },
    {
        key: 'time_to_value',
        area: 'behavior',
        label: 'Time to first value',
        goalVerb: 'Reduce',
        metric: 'time to first key action',
        defaultTarget: 25,
        events: ['signed up', 'key action performed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['saas', 'devtools'],
    },
    {
        key: 'ai_cost_per_user',
        area: 'behavior',
        label: 'AI cost per user',
        goalVerb: 'Reduce',
        metric: 'AI cost per user',
        defaultTarget: 20,
        events: ['$ai_generation'],
        products: [ProductKey.AI_OBSERVABILITY, ProductKey.PRODUCT_ANALYTICS],
        industries: ['ai'],
    },
    {
        key: 'ai_answer_quality',
        area: 'behavior',
        label: 'Answer quality',
        goalVerb: 'Increase',
        metric: 'positive feedback on AI answers',
        defaultTarget: 15,
        events: ['$ai_generation', 'answer rated'],
        products: [ProductKey.AI_OBSERVABILITY, ProductKey.SURVEYS],
        industries: ['ai'],
    },
    {
        key: 'ai_latency',
        area: 'health',
        label: 'AI response time',
        goalVerb: 'Reduce',
        metric: 'AI response time',
        defaultTarget: 20,
        events: ['$ai_generation'],
        products: [ProductKey.AI_OBSERVABILITY],
        industries: ['ai'],
    },
    {
        key: 'verification_completion',
        area: 'behavior',
        label: 'Sign-up verification',
        goalVerb: 'Increase',
        metric: 'verification completion',
        defaultTarget: 15,
        events: ['verification started', 'verification completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['fintech'],
    },
    {
        key: 'payment_success',
        area: 'behavior',
        label: 'Successful payments',
        goalVerb: 'Increase',
        metric: 'payment success rate',
        defaultTarget: 5,
        events: ['payment started', 'payment succeeded', 'payment failed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.ERROR_TRACKING],
        industries: ['fintech', 'ecommerce'],
    },
    {
        key: 'booking_completion',
        area: 'behavior',
        label: 'Appointment booking',
        goalVerb: 'Increase',
        metric: 'appointment booking completion',
        defaultTarget: 15,
        events: ['booking started', 'appointment booked'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['health'],
    },
    {
        key: 'missed_appointments',
        area: 'behavior',
        label: 'Missed appointments',
        goalVerb: 'Reduce',
        metric: 'missed appointments',
        defaultTarget: 20,
        events: ['appointment booked', 'appointment attended'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
        industries: ['health'],
    },
    {
        key: 'course_completion',
        area: 'behavior',
        label: 'Course completion',
        goalVerb: 'Increase',
        metric: 'course completion',
        defaultTarget: 15,
        events: ['lesson started', 'course completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['education'],
    },
    {
        key: 'weekly_learners',
        area: 'behavior',
        label: 'Weekly returning learners',
        goalVerb: 'Increase',
        metric: 'learners who return each week',
        defaultTarget: 10,
        events: ['lesson started'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
        industries: ['education'],
    },
    {
        key: 'subscriber_conversion',
        area: 'behavior',
        label: 'Reader to subscriber',
        goalVerb: 'Increase',
        metric: 'reader to subscriber conversion',
        defaultTarget: 10,
        events: ['article viewed', 'subscription started'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
        industries: ['media'],
    },
    {
        key: 'read_through',
        area: 'behavior',
        label: 'Read-through rate',
        goalVerb: 'Increase',
        metric: 'read-through rate',
        defaultTarget: 15,
        events: ['article viewed', 'article finished'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.WEB_ANALYTICS],
        industries: ['media'],
    },
    {
        key: 'search_to_purchase',
        area: 'behavior',
        label: 'Search to purchase',
        goalVerb: 'Increase',
        metric: 'search to purchase conversion',
        defaultTarget: 10,
        events: ['search performed', 'listing viewed', 'purchase completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['marketplace'],
    },
    {
        key: 'seller_activation',
        area: 'behavior',
        label: 'Seller activation',
        goalVerb: 'Increase',
        metric: 'sellers who publish a first listing',
        defaultTarget: 20,
        events: ['seller signed up', 'listing published'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
        industries: ['marketplace'],
    },
    {
        key: 'referral_rate',
        area: 'behavior',
        label: 'Referrals',
        goalVerb: 'Increase',
        metric: 'referral rate',
        defaultTarget: 10,
        events: ['invite sent', 'invite accepted'],
        products: [ProductKey.PRODUCT_ANALYTICS],
        industries: ['social'],
    },
    {
        key: 'content_creation',
        area: 'behavior',
        label: 'Posts per user',
        goalVerb: 'Increase',
        metric: 'posts per active user',
        defaultTarget: 15,
        events: ['post created'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
        industries: ['social'],
    },
    {
        key: 'day7_retention',
        area: 'behavior',
        label: 'Day 7 retention',
        goalVerb: 'Increase',
        metric: 'day 7 retention',
        defaultTarget: 10,
        events: ['game started', 'session started'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
        industries: ['gaming'],
    },
    {
        key: 'level_completion',
        area: 'behavior',
        label: 'Level completion',
        goalVerb: 'Increase',
        metric: 'level completion',
        defaultTarget: 15,
        events: ['level started', 'level completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['gaming'],
    },
    {
        key: 'in_app_purchases',
        area: 'behavior',
        label: 'In-app purchases',
        goalVerb: 'Increase',
        metric: 'players who make a purchase',
        defaultTarget: 10,
        events: ['purchase completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.EXPERIMENTS],
        industries: ['gaming'],
    },
    {
        key: 'first_api_call',
        area: 'behavior',
        label: 'Sign-up to first API call',
        goalVerb: 'Increase',
        metric: 'sign-ups that make a first API call',
        defaultTarget: 20,
        events: ['signed up', 'api key created', 'first api call'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['devtools'],
    },
    {
        key: 'docs_to_signup',
        area: 'behavior',
        label: 'Docs to sign-up',
        goalVerb: 'Increase',
        metric: 'docs visitor to sign-up conversion',
        defaultTarget: 10,
        events: ['$pageview', 'signed up'],
        products: [ProductKey.WEB_ANALYTICS, ProductKey.PRODUCT_ANALYTICS],
        industries: ['devtools'],
    },
    {
        key: 'booking_conversion',
        area: 'behavior',
        label: 'Search to booking',
        goalVerb: 'Increase',
        metric: 'search to booking conversion',
        defaultTarget: 10,
        events: ['search performed', 'booking completed'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY],
        industries: ['travel'],
    },
    {
        key: 'cancellations',
        area: 'behavior',
        label: 'Booking cancellations',
        goalVerb: 'Reduce',
        metric: 'booking cancellations',
        defaultTarget: 15,
        events: ['booking completed', 'booking canceled'],
        products: [ProductKey.PRODUCT_ANALYTICS, ProductKey.SURVEYS],
        industries: ['travel'],
    },
]

export const INDUSTRY_LABELS: Record<Industry, string> = {
    ecommerce: 'E-commerce',
    saas: 'B2B software',
    ai: 'AI app',
    fintech: 'Finance and payments',
    health: 'Health',
    education: 'Education',
    media: 'Media and content',
    marketplace: 'Marketplace',
    social: 'Social or community',
    gaming: 'Gaming',
    devtools: 'Developer tools',
    travel: 'Travel and booking',
    other: 'Something else',
}

/** Goals written for one industry, shown first. */
export function industryFocusOptions(industry: Industry | null): FocusOption[] {
    return FOCUS_OPTIONS.filter((option) => industry && option.industries?.includes(industry))
}

/** Goals that apply to any product, grouped by area. */
export function generalFocusOptions(area: FocusArea): FocusOption[] {
    return FOCUS_OPTIONS.filter((option) => option.area === area && !option.industries)
}

export function goalSentence(focus: FocusOption, target: number): string {
    if (focus.custom) {
        return focus.metric
    }
    return `${focus.goalVerb} ${focus.metric} by ${target}%`
}

const PLATFORM_NOUNS: Record<Platform, string> = { web: 'web app', mobile: 'mobile app', server: 'backend service' }

export function agentInstallPrompt(
    focus: FocusOption | null,
    target: number,
    platforms: Platform[],
    events: string[]
): string {
    const where = platforms.length > 0 ? platforms.map((platform) => PLATFORM_NOUNS[platform]).join(' and ') : 'project'
    const lines = [`Install PostHog in this ${where} using the PostHog MCP.`]
    if (focus && events.length > 0) {
        const goal = focus.custom
            ? `My first goal is: "${focus.metric}"`
            : `I want to ${goalSentence(focus, target).toLowerCase()}`
        lines.push(
            `${goal}, so also capture these events where they happen: ${events.map((event) => `"${event}"`).join(', ')}.`
        )
    } else if (focus?.custom) {
        lines.push(`My first goal is: "${focus.metric}". Suggest the events that would measure it, and capture them.`)
    }
    lines.push('Then open a pull request with the changes.')
    return lines.join(' ')
}
