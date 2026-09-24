import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab, FileSystemIconColor } from '~/types'

export type OsAppStatus = 'released' | 'beta' | 'alpha' | 'unreleased'

export type OsJob = 'understand' | 'watch' | 'ship' | 'health' | 'ai' | 'automate' | 'data' | 'more'

export interface OsApp {
    /** The `UserProductList` product path for store apps, or a `system:` key for a page outside the product tree. */
    key: string
    name: string
    /** The last segment of the store listing URL. */
    slug: string
    href: string
    description: string | null
    status: OsAppStatus
    job: OsJob
    iconType?: FileSystemIconType
    iconColor?: FileSystemIconColor
    system: boolean
}

export interface OsStoreSection {
    key: string
    title: string
    apps: OsApp[]
}

export function osAppSlug(name: string): string {
    return name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
}

// Pages outside the product tree that windows often show, so the dock can give them an icon. The store
// does not list them, because they are always there.
export const OS_SYSTEM_APPS: OsApp[] = [
    {
        key: 'system:activity',
        name: 'Activity',
        href: urls.activity(ActivityTab.ExploreEvents),
        description: 'See events as they come in and explore everything your project has captured.',
        iconType: 'activity',
    },
    {
        key: 'system:ai',
        name: 'PostHog AI',
        href: urls.ai(),
        description: 'Ask questions about your data and get insights, SQL and answers back.',
        iconType: 'chat',
    },
    {
        key: 'system:settings',
        name: 'Settings',
        href: urls.settings(),
        description: 'Manage your project, organization and account.',
        iconType: 'settings',
    },
].map(
    (app): OsApp => ({
        ...app,
        iconType: app.iconType as FileSystemIconType,
        slug: osAppSlug(app.name),
        status: 'released',
        job: 'more',
        system: true,
    })
)

// Apps grouped by the job the user is doing. Product paths are the tree item names in `products.tsx`;
// an app missing here falls back to its sidebar category.
const JOB_BY_PATH: Record<string, OsJob> = {
    'Product analytics': 'understand',
    'Web analytics': 'understand',
    Dashboards: 'understand',
    'Customer analytics': 'understand',
    'Marketing analytics': 'understand',
    Pulse: 'understand',
    'Identity matching': 'understand',
    'Session replay': 'watch',
    Heatmaps: 'watch',
    'Replay vision': 'watch',
    Surveys: 'watch',
    'User research': 'watch',
    Support: 'watch',
    'Feature flags': 'ship',
    Experiments: 'ship',
    'Early access features': 'ship',
    'Product tours': 'ship',
    Links: 'ship',
    Toolbar: 'ship',
    'Error tracking': 'health',
    Logs: 'health',
    Metrics: 'health',
    Tracing: 'health',
    'Live Debugger': 'health',
    'Engineering analytics': 'health',
    'Code review': 'health',
    'Visual review': 'health',
    'LLM analytics': 'ai',
    Playground: 'ai',
    Clusters: 'ai',
    Datasets: 'ai',
    Evaluations: 'ai',
    Taggers: 'ai',
    Prompts: 'ai',
    'AI gateway': 'ai',
    'MCP analytics': 'ai',
    'MCP servers': 'ai',
    'Business knowledge': 'ai',
    Skills: 'ai',
    Tasks: 'ai',
    Inbox: 'ai',
    Wizard: 'ai',
    Workflows: 'automate',
    Broadcasts: 'automate',
    'Web scripts': 'automate',
    'SQL editor': 'data',
    'Data warehouse': 'data',
    'Data catalog': 'data',
    Endpoints: 'data',
    Apps: 'data',
}

const JOB_BY_CATEGORY: Record<string, OsJob> = {
    Analytics: 'understand',
    Behavior: 'watch',
    Features: 'ship',
    'App monitoring': 'health',
    'AI engineering': 'ai',
}

const JOB_TITLES: [OsJob, string][] = [
    ['understand', 'Understand usage'],
    ['watch', 'Watch and ask users'],
    ['ship', 'Ship and test'],
    ['health', 'Keep production healthy'],
    ['ai', 'Build with AI'],
    ['automate', 'Automate and reach users'],
    ['data', 'Query and move data'],
    ['more', 'More apps'],
]

export const OS_JOB_TITLE: Record<OsJob, string> = Object.fromEntries(JOB_TITLES) as Record<OsJob, string>

function statusOf(item: FileSystemImport): OsAppStatus {
    if (item.category === 'Unreleased') {
        return 'unreleased'
    }
    return item.tags?.[0] ?? 'released'
}

/**
 * The apps the store can install: product tree items the user can see. An app behind a feature flag
 * stays out until the flag is on, and an app the user has no access to stays out too, the same as
 * in the sidebar's "My tools".
 */
export function osCatalogApps(
    products: FileSystemImport[],
    featureFlags: Record<string, boolean | string | undefined>,
    describe: (item: FileSystemImport) => string | null = () => null
): OsApp[] {
    const apps = new Map<string, OsApp>()
    for (const item of products) {
        if (
            !item.href ||
            apps.has(item.path) ||
            (item.flag && !featureFlags[item.flag]) ||
            getProductAccessDisabledReason(item)
        ) {
            continue
        }
        const name = item.displayLabel || unescapePath(splitPath(item.path).pop() ?? item.path)
        apps.set(item.path, {
            key: item.path,
            name,
            slug: osAppSlug(name),
            href: item.href,
            description: describe(item),
            status: statusOf(item),
            job: JOB_BY_PATH[item.path] ?? JOB_BY_CATEGORY[item.category ?? ''] ?? 'more',
            iconType: item.iconType ?? (item.type as FileSystemIconType | undefined),
            iconColor: item.iconColor,
            system: false,
        })
    }
    return [...apps.values()]
}

const byName = (a: OsApp, b: OsApp): number => a.name.localeCompare(b.name, undefined, { sensitivity: 'accent' })

/** The store front page: released apps by job, then Beta and Labs (alpha and unreleased). */
export function osStoreSections(apps: OsApp[]): OsStoreSection[] {
    const released = apps.filter((app) => app.status === 'released')
    const sections: OsStoreSection[] = JOB_TITLES.map(([job, title]) => ({
        key: job,
        title,
        apps: released.filter((app) => app.job === job).sort(byName),
    }))
    sections.push(
        { key: 'beta', title: 'Beta', apps: apps.filter((app) => app.status === 'beta').sort(byName) },
        {
            key: 'labs',
            title: 'Labs',
            apps: apps.filter((app) => app.status === 'alpha' || app.status === 'unreleased').sort(byName),
        }
    )
    return sections.filter((section) => section.apps.length > 0)
}
