import posthog from 'posthog-js'

import { Heading, Item, ItemContent, ItemDescription, ItemGroup, ItemTitle, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

interface StackProduct {
    // pinned: sent as the `product` property of 'warehouse stack map clicked'
    key: string
    name: string
    description: string
    // Without a link, the tool shows as plain text: it has no page, or its page is behind a flag this person lacks.
    href?: string
}

interface StackStage {
    title: string
    products: StackProduct[]
}

function stackStages(dataQualityEnabled: boolean, selfDrivingEnabled: boolean): StackStage[] {
    return [
        {
            title: 'Bring data in',
            products: [
                {
                    key: 'sources',
                    name: 'Sources',
                    description: 'Sync Stripe, HubSpot, Zendesk, ad platforms and databases.',
                    href: urls.sources(),
                },
            ],
        },
        {
            title: 'Store',
            products: [
                {
                    key: 'warehouse',
                    name: 'Warehouse',
                    description: 'External + PostHog data stored side-by-side.',
                },
            ],
        },
        {
            title: 'Govern',
            products: [
                {
                    key: 'semantic_layer',
                    name: 'Semantic layer',
                    description: 'Definitions for your data that you and your agents understand.',
                    href: urls.dataCatalog(),
                },
                {
                    key: 'data_quality',
                    name: 'Data quality',
                    description: "Set up checks to make sure the data you're working from is accurate.",
                    href: dataQualityEnabled ? urls.models('data-quality') : undefined,
                },
            ],
        },
        {
            title: 'Analyze',
            products: [
                {
                    key: 'sql_editor',
                    name: 'PostHog AI + SQL editor',
                    description: 'Ask in plain English and it writes and runs the SQL, or write SQL yourself.',
                    href: urls.sqlEditor(),
                },
                {
                    key: 'business_intelligence',
                    name: 'Business intelligence',
                    description: 'Turn results into insights and dashboards for your team.',
                    href: urls.businessIntelligence(),
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
                {
                    key: 'self_driving',
                    name: 'Self-driving',
                    description: 'Let PostHog agents act on your data to improve your product automatically.',
                    href: selfDrivingEnabled ? urls.inbox() : undefined,
                },
            ],
        },
    ]
}

export function WarehouseStackMap(): JSX.Element {
    const dataQualityEnabled = useFeatureFlag('DATA_QUALITY_CHECKS')
    const selfDrivingEnabled = useFeatureFlag('PRODUCT_AUTONOMY')
    const stages = stackStages(dataQualityEnabled, selfDrivingEnabled)

    return (
        <section aria-labelledby="warehouse-stack-map" className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Heading render={<h2 id="warehouse-stack-map" />} size="base" className="m-0">
                    How the data stack fits together
                </Heading>
                <Text size="sm" variant="muted">
                    A complete data stack in PostHog. Data you bring in is ready to use straight away across every tool,
                    with no pipelines to build and maintain.
                </Text>
            </div>
            <ol className="m-0 grid list-none gap-4 rounded-lg border border-border p-4 @2xl/warehouse-home:grid-cols-3 @5xl/warehouse-home:grid-cols-5">
                {stages.map((stage, index) => (
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
                                    {...(product.href
                                        ? {
                                              // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
                                              className: 'text-foreground hover:bg-fill-hover hover:text-foreground',
                                              render: (
                                                  <LinkPrimitive
                                                      to={product.href}
                                                      data-attr={`warehouse-stack-map-${product.key}`}
                                                      onClick={() =>
                                                          posthog.capture('warehouse stack map clicked', {
                                                              product: product.key,
                                                          })
                                                      }
                                                  />
                                              ),
                                          }
                                        : {})}
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
