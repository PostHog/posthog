import { IconInfo } from '@posthog/icons'
import { LemonTable, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { compactNumber } from 'lib/utils'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { getTierDescription } from './BillingProduct'

export interface ProductPricingTierSubrows {
    columns: {
        title: string
        dataIndex: string
    }[]
    rows: TableTierSubrow[]
}

type TableTierSubrow = {
    productName: string
    price: string
    usage: string
    total: string
    projectedTotal: string
}

type TableTierDatum = {
    volume: string
    basePrice: string
    usage: string
    total: string
    projectedTotal: string
    subrows: ProductPricingTierSubrows
}

function Subrows(props: ProductPricingTierSubrows): JSX.Element {
    return <LemonTable dataSource={props.rows} columns={props.columns} embedded showHeader={false} />
}

export const BillingProductPricingTable = ({
    product,
}: {
    product: BillingProductV2Type
    usageKey?: string
}): JSX.Element => {
    const { billing } = useValues(billingLogic)

    const tableColumns = [
        {
            title: `Priced per ${product.unit}`,
            dataIndex: 'volume',
            render: (_, item: TableTierDatum) => <h4 className="font-bold mb-0">{item.volume}</h4>,
        },
        { title: 'Price', dataIndex: 'basePrice' },
        { title: 'Current Usage', dataIndex: 'usage' },
        {
            title: 'Total',
            dataIndex: 'total',
            render: (_, item: TableTierDatum) => <span className="font-bold mb-0 text-default">{item.total}</span>,
        },
        { title: 'Projected Total', dataIndex: 'projectedTotal' },
    ]

    const subscribedAddons = product.addons?.filter((addon) => addon.subscribed || addon.inclusion_only)

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData: TableTierDatum[] | undefined =
        product.tiers && product.tiers.length > 0
            ? product.tiers
                  ?.map((tier, i) => {
                      const subrows: ProductPricingTierSubrows = {
                          rows:
                              subscribedAddons?.length > 0
                                  ? [
                                        {
                                            productName: 'Base price',
                                            usage: compactNumber(tier.current_usage),
                                            price: `$${tier.unit_amount_usd}`,
                                            total: `$${tier.current_amount_usd || '0.00'}`,
                                            projectedTotal: `$${tier.projected_amount_usd || '0.00'}`,
                                        },
                                        ...(subscribedAddons?.map((addon) => ({
                                            productName: addon.name,
                                            usage: compactNumber(addon.tiers?.[i]?.current_usage || 0),
                                            price: `$${addon.tiers?.[i]?.unit_amount_usd || '0.00'}`,
                                            total: `$${addon.tiers?.[i]?.current_amount_usd || '0.00'}`,
                                            projectedTotal: `$${addon.tiers?.[i]?.projected_amount_usd || '0.00'}`,
                                        })) ?? []),
                                    ]
                                  : [],
                          columns: [
                              { title: `Product name`, dataIndex: 'productName' },
                              {
                                  title: 'Price',
                                  dataIndex: 'price',
                              },
                              { title: 'Current Usage', dataIndex: 'usage' },
                              { title: 'Total', dataIndex: 'total' },
                              { title: 'Projected Total', dataIndex: 'projectedTotal' },
                          ],
                      }
                      // take the tier.current_amount_usd and add it to the same tier level for all the addons
                      const totalForTier =
                          parseFloat(tier.current_amount_usd || '') +
                          (product.addons?.reduce(
                              (acc, addon) => acc + parseFloat(addon.tiers?.[i]?.current_amount_usd || ''),
                              0
                              // if there aren't any addons we get NaN from the above, so we need to default to 0
                          ) || 0)
                      const projectedTotalForTier =
                          (parseFloat(tier.projected_amount_usd || '') || 0) +
                          product.addons?.reduce(
                              (acc, addon) => acc + (parseFloat(addon.tiers?.[i]?.projected_amount_usd || '') || 0),
                              0
                          )

                      const tierData = {
                          volume: product.tiers // this is silly because we know there are tiers since we check above, but typescript doesn't
                              ? getTierDescription(product.tiers, i, product, billing?.billing_period?.interval || '')
                              : '',
                          basePrice:
                              tier.unit_amount_usd !== '0'
                                  ? `$${tier.unit_amount_usd}${subscribedAddons?.length > 0 ? ' + addons' : ''}`
                                  : 'Free',
                          usage: compactNumber(tier.current_usage),
                          total: `$${totalForTier.toFixed(2) || '0.00'}`,
                          projectedTotal: `$${projectedTotalForTier.toFixed(2) || '0.00'}`,
                          subrows: subrows,
                      }
                      return tierData
                  })
                  // Add a row at the end for the total
                  .concat([
                      {
                          volume: 'Total',
                          basePrice: '',
                          usage: '',
                          total: `$${product.current_amount_usd || '0.00'}`,
                          projectedTotal: `$${product.projected_amount_usd || '0.00'}`,
                          subrows: { rows: [], columns: [] },
                      },
                  ])
            : undefined

    if (billing?.discount_percent && parseFloat(product.projected_amount_usd || '')) {
        // If there is a discount, add a row for the total after discount if there is also a projected amount
        tableTierData?.push({
            volume: 'Total after discount',
            basePrice: '',
            usage: '',
            total: `$${
                (parseInt(product.current_amount_usd || '0') * (1 - billing?.discount_percent / 100)).toFixed(2) ||
                '0.00'
            }`,
            projectedTotal: `$${
                (
                    parseInt(product.projected_amount_usd || '0') -
                    parseInt(product.projected_amount_usd || '0') * (billing?.discount_percent / 100)
                ).toFixed(2) || '0.00'
            }`,
            subrows: { rows: [], columns: [] },
        })
    }

    return (
        <div className="pl-16 pb-8">
            {product.tiered && tableTierData ? (
                <>
                    <LemonTable
                        stealth
                        embedded
                        size="small"
                        uppercaseHeader={false}
                        columns={tableColumns}
                        dataSource={tableTierData}
                        expandable={{
                            expandedRowRender: function renderExpand(row) {
                                return row.subrows?.rows?.length ? <Subrows {...row.subrows} /> : null
                            },
                            rowExpandable: (row) => !!row.subrows?.rows?.length,
                        }}
                    />
                    {product.type === 'feature_flags' && (
                        <p className="mt-4 ml-0 text-sm text-muted italic">
                            <IconInfo className="mr-1" />
                            Using local evaluation? Here's{' '}
                            <Link
                                to="https://posthog.com/docs/feature-flags/bootstrapping-and-local-evaluation#server-side-local-evaluation"
                                className="italic"
                            >
                                how we calculate usage
                            </Link>
                            .
                        </p>
                    )}
                </>
            ) : (
                <LemonTable
                    stealth
                    embedded
                    size="small"
                    uppercaseHeader={false}
                    columns={[
                        { title: '', dataIndex: 'name' },
                        { title: 'Total', dataIndex: 'total' },
                    ]}
                    dataSource={[
                        {
                            name: product.name,
                            total: product.unit_amount_usd,
                        },
                    ]}
                />
            )}
        </div>
    )
}
