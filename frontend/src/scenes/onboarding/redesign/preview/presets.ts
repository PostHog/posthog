import { type ProductKey } from '~/queries/schema/schema-general'

import { type OnboardingStepKey } from '../onboardingLogic'
import { buildEventFeed } from './eventStreams'
import { type PreviewConfig, type SidebarSection } from './types'

export interface PreviewContext {
    orgName: string
    products: ProductKey[]
    logoUrl?: string | null
    userName?: string
    archetypeId?: string | null
}

const PROJECT_SECTION: SidebarSection = {
    title: 'Project',
    items: [
        { label: 'Home', iconKey: 'home', active: true },
        { label: 'Inbox', iconKey: 'inbox' },
        { label: 'Activity', iconKey: 'activity' },
        { label: 'Data', iconKey: 'data', expandable: true },
        { label: 'Files', iconKey: 'files', expandable: true },
        { label: 'Apps', iconKey: 'apps', expandable: true },
        { label: 'Starred', iconKey: 'starred', expandable: true },
    ],
}

const DEFAULT_SECTIONS: SidebarSection[] = [PROJECT_SECTION]

/** Clone the project sidebar with a single item (matched by iconKey) marked active. */
function sectionsWithActive(activeIconKey: string): SidebarSection[] {
    return [
        {
            title: PROJECT_SECTION.title,
            items: PROJECT_SECTION.items.map((item) => ({ ...item, active: item.iconKey === activeIconKey })),
        },
    ]
}

const DEFAULT_FOOTER = [
    { label: 'Notifications', iconKey: 'notifications' },
    { label: 'Settings', iconKey: 'gear' },
    { label: 'Help', iconKey: 'help' },
]

const orgIdentity = (ctx: PreviewContext): PreviewConfig['org'] => ({
    name: ctx.orgName.trim(),
    logoUrl: ctx.logoUrl ?? null,
})

const dashboardPage = (): PreviewConfig['page'] => ({
    kind: 'dashboard',
    metrics: [
        { label: 'Unique visitors', value: '48,291', delta: '12.4%', deltaPositive: true },
        { label: 'Pageviews', value: '193k', delta: '8.1%', deltaPositive: true },
        { label: 'Conversion', value: '3.2%', delta: '0.4%', deltaPositive: true },
    ],
    charts: [
        { title: 'Pageviews · trends', kind: 'trend' },
        { title: 'Top events', kind: 'bars' },
        {
            title: 'Top pages',
            kind: 'table',
            rows: [
                { label: '/home', value: '48,291' },
                { label: '/pricing', value: '32,104' },
                { label: '/docs', value: '18,227' },
                { label: '/blog', value: '12,840' },
            ],
        },
    ],
})

const homePage = (ctx: PreviewContext): PreviewConfig['page'] => ({
    kind: 'home',
    greetingName: ctx.userName?.trim().split(' ')[0] || '',
    pinnedDashboards: [
        { label: 'Weekly active users' },
        { label: 'Activation funnel' },
        { label: 'Revenue overview' },
        { label: 'Feature adoption' },
    ],
    recents: [{ label: 'Checkout drop-off' }, { label: 'Mobile sign-ups' }, { label: 'Pricing page views' }],
    starred: [],
})

export const PREVIEW_PRESETS: Record<OnboardingStepKey, (ctx: PreviewContext) => PreviewConfig> = {
    create_org: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { sections: DEFAULT_SECTIONS, footerItems: DEFAULT_FOOTER },
        page: homePage(ctx),
    }),
    company: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { sections: DEFAULT_SECTIONS, footerItems: DEFAULT_FOOTER },
        page: ctx.products.length
            ? dashboardPage()
            : {
                  kind: 'empty',
                  title: "Pick what you're building",
                  subtitle: "We'll set up the right products for you.",
              },
    }),
    install: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { sections: sectionsWithActive('activity'), footerItems: DEFAULT_FOOTER },
        // Data starts flowing as soon as the SDK is in — show a live, archetype-themed event stream.
        page: { kind: 'activity', events: buildEventFeed(ctx.archetypeId) },
    }),
    configure: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { sections: DEFAULT_SECTIONS, footerItems: DEFAULT_FOOTER },
        page: ctx.products.length
            ? dashboardPage()
            : { kind: 'empty', title: 'Configure PostHog', subtitle: 'Set up your products.' },
    }),
    learn: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { sections: DEFAULT_SECTIONS, footerItems: DEFAULT_FOOTER },
        page: ctx.products.length
            ? dashboardPage()
            : { kind: 'empty', title: 'Learn PostHog', subtitle: 'Explore key features.' },
    }),
    done: (ctx) => ({
        org: orgIdentity(ctx),
        sidebar: { sections: DEFAULT_SECTIONS, footerItems: DEFAULT_FOOTER },
        page: dashboardPage(),
    }),
}

export function buildPreviewConfig(stepKey: OnboardingStepKey, ctx: PreviewContext): PreviewConfig {
    return (PREVIEW_PRESETS[stepKey] ?? PREVIEW_PRESETS.create_org)(ctx)
}
