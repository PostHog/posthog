import { useMemo } from 'react'

import {
    IconApps,
    IconBuilding,
    IconCheckbox,
    IconFeatures,
    IconFilter,
    IconMegaphone,
    IconNotebook,
    IconPeople,
    IconPerson,
    IconPulse,
    IconSupport,
} from '@posthog/icons'

import { ProductIconWrapper } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SIDEBAR_GROUP_META, SidebarProductMeta, sidebarProductCopy } from '~/layout/panel-layout/sidebarProductMeta'
import { FileSystemIconColor } from '~/types'

import { TodayPaneRow } from './TodayPaneRow'
import { TodayPeopleRow } from './todayPeopleLogic'
import { TodayPeopleStaticRowKey } from './todayPeopleModel'
import { TodayExplainerPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

function colored(icon: JSX.Element, product: string): JSX.Element {
    const color: FileSystemIconColor = [`var(--color-product-${product}-light)`, `var(--color-product-${product}-dark)`]
    return (
        <ProductIconWrapper type="default_icon_type" colorOverride={color}>
            {icon}
        </ProductIconWrapper>
    )
}

const ROW_ICONS: Record<TodayPeopleStaticRowKey, JSX.Element> = {
    overview: <IconApps />,
    feed: <IconPulse />,
    tasks: <IconCheckbox />,
    persons: colored(<IconPerson />, 'product-analytics'),
    accounts: colored(<IconBuilding />, 'sources'),
    cohorts: colored(<IconPeople />, 'data-warehouse'),
    journeys: colored(<IconFilter />, 'customer-analytics'),
    notes: <IconNotebook />,
    announcements: <IconMegaphone />,
    feature_requests: <IconFeatures />,
    support: <IconSupport />,
}

const GROUP_ICON = <IconBuilding />

const ROW_EXPLAINERS: Record<TodayPeopleStaticRowKey, SidebarProductMeta> = {
    overview: {
        description:
            'See how your customers use your product. Follow active users, sessions, and signups on one dashboard.',
        example: 'Check how many free users became paying customers this month.',
        docsHref: 'https://posthog.com/docs/customer-analytics',
    },
    feed: {
        description: 'Review the account changes that customer analytics scouts report.',
        example: 'See which accounts changed since last week.',
    },
    tasks: {
        description: 'See the work assigned to you across customer accounts.',
        example: 'Follow up with an account after a call.',
    },
    persons: sidebarProductCopy('Persons'),
    accounts: {
        description: 'Browse the companies that use your product and the activity behind each one.',
        example: SIDEBAR_GROUP_META.example,
    },
    cohorts: { ...sidebarProductCopy('Cohorts'), docsHref: 'https://posthog.com/docs/data/cohorts' },
    journeys: {
        description: 'Map the steps customers take through your product and see where they drop off.',
        example: 'See where new users stop on the way to their first purchase.',
    },
    notes: {
        description: 'Keep notes about your customer accounts in one place, and search them later.',
        example: 'Record what an account asked for on a call.',
    },
    announcements: {
        description: 'Share product news with your customers.',
        example: 'Tell customers about a new feature.',
    },
    feature_requests: {
        description: 'Track what customers ask you to build, and which accounts asked for it.',
        example: 'See which accounts want a new integration.',
    },
    support: {
        description: 'Read and respond to support requests from your customers.',
        example: 'Reply to a customer who reported a bug.',
        docsHref: 'https://posthog.com/docs/support',
    },
}

// Group type names belong to each project, so the copy can only say what a group type is, in the project's own words.
function groupExplainer(label: string): SidebarProductMeta {
    const plural = label.toLowerCase()
    return {
        description: `Your project tracks ${plural} as a group type. Each one collects its own events, properties, and people, so you can look at usage above the level of a single person.`,
        example: `Find the ${plural} with the most activity this month.`,
        docsHref: 'https://posthog.com/docs/product-analytics/group-analytics',
    }
}

export function TodayPeopleNavRow({
    row,
    meta,
    active,
}: {
    row: TodayPeopleRow
    meta?: string
    active: boolean
}): JSX.Element {
    const icon = row.kind === 'static' ? ROW_ICONS[row.key] : GROUP_ICON
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({
            kind: 'explainer',
            label: row.label,
            icon,
            ...(row.kind === 'static' ? ROW_EXPLAINERS[row.key] : groupExplainer(row.label)),
        }),
        [row.kind, row.key, row.label, icon]
    )
    return (
        <TodayPreviewTrigger payload={preview}>
            <TodayPaneRow
                value={`browse:${row.key}`}
                label={row.label}
                meta={meta}
                icon={icon}
                to={row.href}
                active={active}
                dataAttr={`people-sidebar-${row.key}`}
            />
        </TodayPreviewTrigger>
    )
}
