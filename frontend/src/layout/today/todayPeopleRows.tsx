import { useValues } from 'kea'

import {
    IconApps,
    IconBuilding,
    IconCheckbox,
    IconFeatures,
    IconFilter,
    IconGear,
    IconLetter,
    IconMegaphone,
    IconNotebook,
    IconPeople,
    IconPerson,
    IconPulse,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { productHasEffectiveNoneAccess } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { ProductIconWrapper } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SIDEBAR_GROUP_META, SidebarProductMeta, sidebarProductCopy } from '~/layout/panel-layout/sidebarProductMeta'
import type { ResourceType } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlResourceType, FileSystemIconColor } from '~/types'

import { todayShellLogic } from './todayShellLogic'

// pinned: persisted section ids and the `section` property of `people section toggled`.
export type TodayPeopleSection = 'recents' | 'groups' | 'customer-analytics'

/** A titled section under Recents. A row with no section sits on top of the pane. */
export type TodayPeopleRowSection = Exclude<TodayPeopleSection, 'recents'>

export const TODAY_PEOPLE_ROW_SECTION_LABELS: Record<TodayPeopleRowSection, string> = {
    groups: 'Groups',
    'customer-analytics': 'Customer analytics',
}

interface TodayPeopleRowDefinition {
    label: string
    icon: JSX.Element
    iconColor?: FileSystemIconColor
    explainer: SidebarProductMeta
    section: TodayPeopleRowSection | null
    href: () => string
    /** The paths that mark the row active. The href by default. */
    paths?: () => string[]
    /** Whether the pane shows the row. The same flags gate the Customer analytics tabs it replaces. */
    enabled: (featureFlags: FeatureFlagsSet) => boolean
}

const productColor = (product: string): FileSystemIconColor => [
    `var(--color-product-${product}-light)`,
    `var(--color-product-${product}-dark)`,
]

const always = (): boolean => true

/** On with the Customer analytics flag and every flag given. */
const withCustomerAnalytics =
    (...flags: (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS][]) =>
    (featureFlags: FeatureFlagsSet): boolean =>
        !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS] && flags.every((flag) => !!featureFlags[flag])

/**
 * Every fixed row of the People pane, in pane order. Group types sit after Accounts, and `peopleSidebarRows` adds
 * them. One place holds what a row is, so the pane, its hover cards and the pages' headers cannot drift apart.
 */
// pinned: the keys are part of the row's `people-sidebar-<row>` data-attr.
export const TODAY_PEOPLE_ROWS = {
    overview: {
        label: 'Overview',
        icon: <IconApps />,
        explainer: {
            description:
                'See how your customers use your product. Follow active users, sessions, and signups on one dashboard.',
            example: 'Check how many free users became paying customers this month.',
            docsHref: 'https://posthog.com/docs/customer-analytics',
        },
        section: null,
        href: () => urls.customerAnalyticsDashboard(),
        enabled: withCustomerAnalytics(),
    },
    feed: {
        label: 'Feed',
        icon: <IconPulse />,
        explainer: {
            description: 'Review the account changes that customer analytics scouts report.',
            example: 'See which accounts changed since last week.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsFeed(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP),
    },
    tasks: {
        label: 'Tasks',
        icon: <IconCheckbox />,
        explainer: {
            description: 'See the work assigned to you across customer accounts.',
            example: 'Follow up with an account after a call.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsTasks(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS),
    },
    persons: {
        label: 'Persons',
        icon: <IconPerson />,
        iconColor: productColor('product-analytics'),
        explainer: sidebarProductCopy('Persons'),
        section: null,
        href: () => urls.persons(),
        paths: () => [urls.persons(), '/person'],
        enabled: always,
    },
    // With customer-analytics-csp this is the Customer analytics accounts page. Without it, `peopleSidebarRows`
    // points it at the account group type.
    accounts: {
        label: 'Accounts',
        icon: <IconBuilding />,
        iconColor: productColor('sources'),
        explainer: {
            description: 'Browse the companies that use your product and the activity behind each one.',
            example: SIDEBAR_GROUP_META.example,
        },
        section: null,
        href: () => urls.customerAnalyticsAccounts(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP),
    },
    cohorts: {
        label: 'Cohorts',
        icon: <IconPeople />,
        iconColor: productColor('data-warehouse'),
        explainer: { ...sidebarProductCopy('Cohorts'), docsHref: 'https://posthog.com/docs/data/cohorts' },
        section: null,
        href: () => urls.cohorts(),
        enabled: always,
    },
    journeys: {
        label: 'Journeys',
        icon: <IconFilter />,
        iconColor: productColor('customer-analytics'),
        explainer: {
            description: 'Map the steps customers take through your product and see where they drop off.',
            example: 'See where new users stop on the way to their first purchase.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsJourneys(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS),
    },
    product_activity: {
        label: 'Product activity',
        icon: <IconPulse />,
        explainer: {
            description: 'Compare account activity across products and time periods.',
            example: 'See which accounts started using a product this week.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsProductActivity(),
        enabled: withCustomerAnalytics(
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS_DOT_MATRIX
        ),
    },
    notes: {
        label: 'Notes',
        icon: <IconNotebook />,
        explainer: {
            description: 'Keep notes about your customer accounts in one place, and search them later.',
            example: 'Record what an account asked for on a call.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsNotes(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP),
    },
    announcements: {
        label: 'Announcements',
        icon: <IconMegaphone />,
        explainer: {
            description: 'Share product news with your customers.',
            example: 'Tell customers about a new feature.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsAnnouncements(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP),
    },
    feature_requests: {
        label: 'Feature requests',
        icon: <IconFeatures />,
        explainer: {
            description: 'Track what customers ask you to build, and which accounts asked for it.',
            example: 'See which accounts want a new integration.',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsFeatureRequests(),
        enabled: withCustomerAnalytics(FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS),
    },
    configure: {
        label: 'Configure',
        icon: <IconGear />,
        explainer: {
            description:
                'Choose the events and group type that customer analytics uses for its dashboards and accounts.',
            example: 'Pick the event that counts as a signup.',
            docsHref: 'https://posthog.com/docs/customer-analytics',
        },
        section: 'customer-analytics',
        href: () => urls.customerAnalyticsConfiguration(),
        enabled: withCustomerAnalytics(),
    },
    support: {
        label: 'Tickets',
        icon: <IconLetter />,
        explainer: {
            description: 'Read and reply to the support tickets your customers send.',
            example: 'Reply to a customer who reported a bug.',
            docsHref: 'https://posthog.com/docs/support',
        },
        section: null,
        href: () => urls.supportTickets(),
        paths: () => [urls.supportDashboard()],
        // Without Ticket access the page only says access denied.
        enabled: () => !productHasEffectiveNoneAccess(AccessControlResourceType.Ticket),
    },
} satisfies Record<string, TodayPeopleRowDefinition>

export type TodayPeopleStaticRowKey = keyof typeof TODAY_PEOPLE_ROWS

const rowDefinition = (key: TodayPeopleStaticRowKey): TodayPeopleRowDefinition => TODAY_PEOPLE_ROWS[key]

/** Group type rows share one icon. Their names belong to each project. */
export const TODAY_PEOPLE_GROUP_ICON = <IconBuilding />

/** The icon of a People pane row. */
export function todayPeopleRowIcon(key: TodayPeopleStaticRowKey): JSX.Element {
    const { icon, iconColor } = rowDefinition(key)
    return iconColor ? (
        <ProductIconWrapper type="default_icon_type" colorOverride={iconColor}>
            {icon}
        </ProductIconWrapper>
    ) : (
        icon
    )
}

/** The name of a page's People pane row while that pane is open, else null. For selectors, like breadcrumbs. */
export function todayPeopleRowLabel(peoplePaneLinksTabs: boolean, key: TodayPeopleStaticRowKey): string | null {
    return peoplePaneLinksTabs ? rowDefinition(key).label : null
}

export interface TodayPeopleTitle {
    name: string | null
    resourceType: ResourceType
}

/**
 * The scene title of a page while the People pane is open: its row's name and icon, so the header matches the nav.
 * Null from any other pane, so the page keeps its own title. A group type page passes 'group' and keeps its own name.
 */
export function useTodayPeopleTitle(key: TodayPeopleStaticRowKey | 'group'): TodayPeopleTitle | null {
    const { peoplePaneLinksTabs } = useValues(todayShellLogic)
    if (!peoplePaneLinksTabs) {
        return null
    }
    if (key === 'group') {
        return { name: null, resourceType: { type: 'group', forceIcon: TODAY_PEOPLE_GROUP_ICON } }
    }
    const { label, icon, iconColor } = rowDefinition(key)
    return {
        name: label,
        resourceType: { type: 'default_icon_type', forceIcon: icon, forceIconColorOverride: iconColor },
    }
}
