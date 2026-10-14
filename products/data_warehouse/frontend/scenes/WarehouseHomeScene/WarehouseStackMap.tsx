import posthog from 'posthog-js'

import { Heading, Item, ItemContent, ItemDescription, ItemGroup, ItemTitle, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

interface StackProduct {
    // pinned: sent as the `product` property of 'warehouse stack map clicked'
    key: string
    name: string
    description: string
    href: string
}

interface StackStage {
    title: string
    products: StackProduct[]
}

const STAGES: StackStage[] = [
    {
        title: 'Bring data in',
        products: [
            {
                key: 'sources',
                name: 'Sources',
                description: 'Sync Stripe, HubSpot, Zendesk, ad platforms and databases.',
                href: urls.sources(),
            },
            {
                key: 'managed_migrations',
                name: 'Managed migrations',
                description: 'Import historical events from another analytics tool.',
                href: urls.managedMigration(),
            },
        ],
    },
    {
        title: 'Store',
        products: [
            {
                key: 'data_catalog',
                name: 'Data catalog',
                description: 'Every table in your warehouse, PostHog data included.',
                href: urls.dataCatalog(),
            },
        ],
    },
    {
        title: 'Shape',
        products: [
            {
                key: 'sql_editor',
                name: 'SQL editor',
                description: 'Query and join any table, PostHog or external.',
                href: urls.sqlEditor(),
            },
            {
                key: 'models',
                name: 'Models',
                description: 'Save queries as views and materialize them on a schedule.',
                href: urls.models(),
            },
        ],
    },
    {
        title: 'Analyze',
        products: [
            {
                key: 'business_intelligence',
                name: 'Business intelligence',
                description: 'Turn results into insights and dashboards for your team.',
                href: urls.businessIntelligence(),
            },
            {
                key: 'posthog_ai',
                name: 'PostHog AI',
                description: 'Ask in plain English. It writes and runs the SQL.',
                href: urls.ai(),
            },
        ],
    },
    {
        title: 'Act on it',
        products: [
            {
                key: 'destinations',
                name: 'Destinations',
                description: 'Send results to your CRM, ad platforms or another warehouse.',
                href: urls.destinations(),
            },
        ],
    },
]

export function WarehouseStackMap(): JSX.Element {
    return (
        <section aria-labelledby="warehouse-stack-map" className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                <Heading render={<h2 id="warehouse-stack-map" />} size="base" className="m-0">
                    How the data stack fits together
                </Heading>
                <Text size="sm" variant="muted">
                    Every tool here works on the same warehouse, so data you bring in is ready to use straight away.
                </Text>
            </div>
            <ol className="m-0 grid list-none gap-4 rounded-lg border border-border p-4 @2xl/warehouse-home:grid-cols-3 @5xl/warehouse-home:grid-cols-5">
                {STAGES.map((stage, index) => (
                    <li key={stage.title} className="flex flex-col gap-2">
                        <Text size="xs" weight="semibold" variant="muted" className="uppercase">
                            {index + 1}. {stage.title}
                        </Text>
                        <ItemGroup className="gap-2">
                            {stage.products.map((product) => (
                                <Item
                                    key={product.key}
                                    size="sm"
                                    variant="outline"
                                    // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
                                    className="text-foreground hover:bg-fill-hover hover:text-foreground"
                                    render={
                                        <LinkPrimitive
                                            to={product.href}
                                            data-attr={`warehouse-stack-map-${product.key}`}
                                            onClick={() =>
                                                posthog.capture('warehouse stack map clicked', { product: product.key })
                                            }
                                        />
                                    }
                                >
                                    <ItemContent>
                                        <ItemTitle>{product.name}</ItemTitle>
                                        <ItemDescription>{product.description}</ItemDescription>
                                    </ItemContent>
                                </Item>
                            ))}
                        </ItemGroup>
                    </li>
                ))}
            </ol>
        </section>
    )
}
