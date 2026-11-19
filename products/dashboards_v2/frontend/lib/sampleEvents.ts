import type { Weighted } from './sampleInfra'

export interface SampleEvent {
    name: string
    count: number
}

export interface SampleProperty {
    key: string
    type: 'String' | 'Numeric' | 'Boolean' | 'DateTime'
    share: number
    values: Weighted
    events?: string[]
    unseen?: boolean
}

export const SAMPLE_EVENTS: SampleEvent[] = [
    { name: '$pageview', count: 1_842_300 },
    { name: '$pageleave', count: 1_512_900 },
    { name: '$autocapture', count: 968_400 },
    { name: 'insight viewed', count: 152_800 },
    { name: '$screen', count: 126_300 },
    { name: 'logged in', count: 96_310 },
    { name: 'dashboard viewed', count: 88_640 },
    { name: 'file uploaded', count: 23_950 },
    { name: 'signed up', count: 18_420 },
    { name: 'checkout started', count: 12_480 },
    { name: 'purchase completed', count: 7_930 },
    { name: 'invite sent', count: 5_870 },
    { name: 'subscription upgraded', count: 1_260 },
]

const PLANS: Weighted = [
    ['free', 71],
    ['scale', 22],
    ['enterprise', 7],
]
const BROWSERS: Weighted = [
    ['Chrome', 58],
    ['Safari', 21],
    ['Firefox', 9],
    ['Edge', 8],
    ['Samsung Internet', 2],
    ['Opera', 2],
]
const COUNTRIES: Weighted = [
    ['United States', 38],
    ['Germany', 12],
    ['United Kingdom', 11],
    ['India', 9],
    ['France', 7],
    ['Brazil', 6],
    ['Canada', 6],
    ['Netherlands', 4],
    ['Australia', 4],
    ['Japan', 3],
]
const REFERRERS: Weighted = [
    ['$direct', 44],
    ['google.com', 31],
    ['github.com', 9],
    ['news.ycombinator.com', 6],
    ['twitter.com', 5],
    ['linkedin.com', 3],
    ['duckduckgo.com', 2],
]
const UTM_SOURCES: Weighted = [
    ['google', 46],
    ['newsletter', 24],
    ['twitter', 14],
    ['linkedin', 9],
    ['producthunt', 7],
]
const WEB = ['$pageview', '$pageleave', '$autocapture']
const PURCHASE = ['checkout started', 'purchase completed']

export const SAMPLE_EVENT_PROPERTIES: SampleProperty[] = [
    { key: '$browser', type: 'String', share: 0.97, values: BROWSERS },
    {
        key: '$os',
        type: 'String',
        share: 0.97,
        values: [
            ['Mac OS X', 41],
            ['Windows', 33],
            ['iOS', 12],
            ['Android', 9],
            ['Linux', 5],
        ],
    },
    {
        key: '$device_type',
        type: 'String',
        share: 0.97,
        values: [
            ['Desktop', 76],
            ['Mobile', 20],
            ['Tablet', 4],
        ],
    },
    {
        key: '$current_url',
        type: 'String',
        share: 0.94,
        values: [
            ['https://app.example.com/insights', 24],
            ['https://app.example.com/dashboard', 19],
            ['https://example.com/', 17],
            ['https://example.com/pricing', 11],
            ['https://example.com/docs', 10],
            ['https://app.example.com/login', 8],
            ['https://app.example.com/signup', 6],
            ['https://app.example.com/checkout', 5],
        ],
    },
    {
        key: '$pathname',
        type: 'String',
        share: 0.94,
        values: [
            ['/insights', 24],
            ['/dashboard', 19],
            ['/', 17],
            ['/pricing', 11],
            ['/docs', 10],
            ['/login', 8],
            ['/signup', 6],
            ['/checkout', 5],
        ],
    },
    {
        key: '$host',
        type: 'String',
        share: 0.94,
        values: [
            ['app.example.com', 62],
            ['example.com', 38],
        ],
    },
    { key: '$referring_domain', type: 'String', share: 0.91, values: REFERRERS },
    { key: '$geoip_country_name', type: 'String', share: 0.93, values: COUNTRIES },
    {
        key: '$geoip_city_name',
        type: 'String',
        share: 0.88,
        values: [
            ['New York', 9],
            ['London', 8],
            ['San Francisco', 8],
            ['Berlin', 6],
            ['Bengaluru', 5],
            ['Paris', 5],
            ['Toronto', 4],
            ['São Paulo', 4],
            ['Amsterdam', 3],
            ['Sydney', 3],
        ],
    },
    {
        key: '$lib',
        type: 'String',
        share: 1,
        values: [
            ['web', 84],
            ['posthog-ios', 7],
            ['posthog-android', 5],
            ['posthog-node', 4],
        ],
    },
    {
        key: '$screen_width',
        type: 'Numeric',
        share: 0.95,
        values: [
            ['1920', 27],
            ['1440', 22],
            ['1536', 16],
            ['390', 13],
            ['1280', 10],
            ['2560', 7],
            ['414', 5],
        ],
    },
    {
        key: '$screen_height',
        type: 'Numeric',
        share: 0.95,
        values: [
            ['1080', 30],
            ['900', 22],
            ['864', 16],
            ['844', 13],
            ['720', 8],
            ['1440', 7],
            ['896', 4],
        ],
    },
    {
        key: '$session_duration',
        type: 'Numeric',
        share: 0.42,
        events: ['$pageleave'],
        values: [
            ['12', 20],
            ['48', 24],
            ['131', 22],
            ['305', 18],
            ['742', 11],
            ['1860', 5],
        ],
    },
    { key: 'utm_source', type: 'String', share: 0.18, events: WEB, values: UTM_SOURCES },
    {
        key: 'utm_campaign',
        type: 'String',
        share: 0.16,
        events: WEB,
        values: [
            ['spring-launch', 41],
            ['brand-search', 27],
            ['weekly-digest', 20],
            ['retargeting', 12],
        ],
    },
    {
        key: '$feature/new-onboarding',
        type: 'String',
        share: 0.61,
        values: [
            ['control', 50],
            ['test', 50],
        ],
    },
    {
        key: '$feature/checkout-redesign',
        type: 'String',
        share: 0.34,
        values: [
            ['control', 34],
            ['one-page', 33],
            ['express', 33],
        ],
    },
    {
        key: '$screen_name',
        type: 'String',
        share: 1,
        events: ['$screen'],
        values: [
            ['Home', 34],
            ['Insights', 26],
            ['Dashboard', 21],
            ['Settings', 11],
            ['Checkout', 8],
        ],
    },
    { key: 'plan', type: 'String', share: 0.98, events: ['signed up', ...PURCHASE], values: PLANS },
    {
        key: 'signup_method',
        type: 'String',
        share: 1,
        events: ['signed up', 'logged in'],
        values: [
            ['google', 47],
            ['email', 31],
            ['github', 17],
            ['sso', 5],
        ],
    },
    {
        key: 'insight_type',
        type: 'String',
        share: 1,
        events: ['insight viewed'],
        values: [
            ['trends', 46],
            ['funnels', 21],
            ['sql', 14],
            ['retention', 11],
            ['paths', 8],
        ],
    },
    {
        key: 'is_shared',
        type: 'Boolean',
        share: 0.9,
        events: ['insight viewed', 'dashboard viewed'],
        values: [
            ['false', 87],
            ['true', 13],
        ],
    },
    {
        key: 'tile_count',
        type: 'Numeric',
        share: 1,
        events: ['dashboard viewed'],
        values: [
            ['4', 18],
            ['6', 24],
            ['8', 22],
            ['12', 19],
            ['16', 11],
            ['24', 6],
        ],
    },
    {
        key: 'revenue',
        type: 'Numeric',
        share: 1,
        events: ['purchase completed', 'subscription upgraded'],
        values: [
            ['49', 38],
            ['99', 24],
            ['199', 17],
            ['450', 12],
            ['1200', 6],
            ['4800', 3],
        ],
    },
    {
        key: 'cart_value',
        type: 'Numeric',
        share: 1,
        events: ['checkout started'],
        values: [
            ['49', 35],
            ['99', 25],
            ['199', 19],
            ['450', 12],
            ['1200', 6],
            ['4800', 3],
        ],
    },
    {
        key: 'item_count',
        type: 'Numeric',
        share: 0.96,
        events: PURCHASE,
        values: [
            ['1', 61],
            ['2', 22],
            ['3', 10],
            ['5', 5],
            ['10', 2],
        ],
    },
    {
        key: 'currency',
        type: 'String',
        share: 1,
        events: PURCHASE,
        values: [
            ['USD', 64],
            ['EUR', 23],
            ['GBP', 13],
        ],
    },
    {
        key: 'payment_method',
        type: 'String',
        share: 1,
        events: ['purchase completed'],
        values: [
            ['card', 71],
            ['paypal', 14],
            ['apple_pay', 9],
            ['invoice', 6],
        ],
    },
    {
        key: 'coupon_used',
        type: 'Boolean',
        share: 1,
        events: ['purchase completed'],
        values: [
            ['false', 82],
            ['true', 18],
        ],
    },
    {
        key: 'to_plan',
        type: 'String',
        share: 1,
        events: ['subscription upgraded'],
        values: [
            ['scale', 78],
            ['enterprise', 22],
        ],
    },
    {
        key: 'role',
        type: 'String',
        share: 1,
        events: ['invite sent'],
        values: [
            ['member', 81],
            ['admin', 19],
        ],
    },
    {
        key: 'file_type',
        type: 'String',
        share: 1,
        events: ['file uploaded'],
        values: [
            ['csv', 52],
            ['png', 21],
            ['pdf', 15],
            ['json', 12],
        ],
    },
    {
        key: 'file_size_kb',
        type: 'Numeric',
        share: 1,
        events: ['file uploaded'],
        values: [
            ['18', 22],
            ['240', 31],
            ['1024', 25],
            ['5120', 15],
            ['20480', 7],
        ],
    },
    { key: 'legacy_plan', type: 'String', share: 0, values: [], unseen: true },
    { key: 'experiment_group', type: 'String', share: 0, values: [], unseen: true },
    { key: 'page_load_ms', type: 'Numeric', share: 0, values: [], unseen: true },
]

export const SAMPLE_PERSON_PROPERTIES: SampleProperty[] = [
    {
        key: 'email',
        type: 'String',
        share: 0.64,
        values: [
            ['amara@example.com', 3],
            ['jonas@example.com', 3],
            ['priya@example.com', 2],
            ['mateo@example.com', 2],
            ['yuki@example.com', 2],
            ['lena@example.com', 1],
        ],
    },
    { key: 'plan', type: 'String', share: 0.64, values: PLANS },
    {
        key: 'role',
        type: 'String',
        share: 0.52,
        values: [
            ['engineer', 39],
            ['product manager', 23],
            ['founder', 14],
            ['data analyst', 11],
            ['designer', 8],
            ['marketer', 5],
        ],
    },
    {
        key: 'company_size',
        type: 'String',
        share: 0.47,
        values: [
            ['1-10', 34],
            ['11-50', 29],
            ['51-200', 21],
            ['201-1000', 11],
            ['1000+', 5],
        ],
    },
    {
        key: 'industry',
        type: 'String',
        share: 0.38,
        values: [
            ['SaaS', 44],
            ['E-commerce', 19],
            ['Fintech', 14],
            ['Healthcare', 9],
            ['Education', 8],
            ['Gaming', 6],
        ],
    },
    {
        key: 'is_paying',
        type: 'Boolean',
        share: 0.64,
        values: [
            ['false', 71],
            ['true', 29],
        ],
    },
    {
        key: 'seats',
        type: 'Numeric',
        share: 0.31,
        values: [
            ['1', 36],
            ['3', 24],
            ['8', 19],
            ['20', 13],
            ['75', 6],
            ['300', 2],
        ],
    },
    {
        key: 'lifetime_value',
        type: 'Numeric',
        share: 0.29,
        values: [
            ['0', 40],
            ['240', 22],
            ['1180', 18],
            ['4750', 12],
            ['21600', 6],
            ['96000', 2],
        ],
    },
    {
        key: 'created_at',
        type: 'DateTime',
        share: 0.99,
        values: [
            ['2026-10-02T09:14:00Z', 1],
            ['2026-08-19T16:40:00Z', 1],
            ['2026-05-27T11:05:00Z', 1],
            ['2025-12-11T08:22:00Z', 1],
        ],
    },
    { key: '$initial_browser', type: 'String', share: 0.96, values: BROWSERS },
    { key: '$initial_referring_domain', type: 'String', share: 0.9, values: REFERRERS },
    { key: '$initial_utm_source', type: 'String', share: 0.21, values: UTM_SOURCES },
    { key: '$geoip_country_name', type: 'String', share: 0.93, values: COUNTRIES },
    {
        key: '$feature_enrollment/new-onboarding',
        type: 'Boolean',
        share: 0.08,
        values: [
            ['true', 92],
            ['false', 8],
        ],
    },
    { key: 'referral_code', type: 'String', share: 0, values: [], unseen: true },
    { key: 'churned_at', type: 'DateTime', share: 0, values: [], unseen: true },
]

export const SAMPLE_COHORTS = [
    { id: 1, name: 'Paying customers', count: 4_210, isStatic: false },
    { id: 2, name: 'Signed up in the last 30 days', count: 2_945, isStatic: false },
    { id: 3, name: 'Power users', count: 1_863, isStatic: false },
    { id: 4, name: 'Churn risk', count: 612, isStatic: false },
    { id: 5, name: 'Beta testers', count: 320, isStatic: true },
    { id: 6, name: 'Internal team', count: 48, isStatic: true },
]

export const SAMPLE_ACTIONS = [
    { id: 1, name: 'Completed onboarding', description: 'Finished the last step of the setup checklist' },
    { id: 2, name: 'Signed up or logged in', description: 'Any way of starting a session' },
    { id: 3, name: 'Started checkout', description: '' },
    { id: 4, name: 'Viewed pricing', description: 'Pageview of /pricing' },
]
