import { IconArrowRightDown } from '@posthog/icons'
import { LemonBanner, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { compactNumber } from 'lib/utils'

import { BillingProductV2Type, BillingTableTierRow, ProductPricingTierSubrows } from '~/types'

import { billingLogic } from './billingLogic'
import { FeatureFlagUsageNotice, getTierDescription } from './BillingProduct'

function Subrows(props: ProductPricingTierSubrows): JSX.Element {
    return (
        <div className="px-2 pt-4 pb-6">
            <LemonTable dataSource={props.rows} columns={props.columns} embedded showHeader={true} />
        </div>
    )
}

export const BillingProductPricingTable = ({
    product,
}: {
    product: BillingProductV2Type
    usageKey?: string
}): JSX.Element => {
    const { billing } = useValues(billingLogic)

    const tableColumns: LemonTableColumns<BillingTableTierRow> = [
        {
            title: `Priced per ${product.unit}`,
            dataIndex: 'volume',
            render: (_, item: BillingTableTierRow) => <h4 className="font-bold mb-0">{item.volume}</h4>,
        },
        { title: 'Price', dataIndex: 'basePrice' },
        { title: 'Current Usage', dataIndex: 'usage' },
        {
            title: 'Total',
            dataIndex: 'total',
            render: (_, item: BillingTableTierRow) => (
                <span className="font-bold mb-0 text-text-3000">{item.total}</span>
            ),
        },
        { title: 'Projected Total', dataIndex: 'projectedTotal' },
    ]

    const subscribedAddons = product.addons?.filter(
        (addon) => addon.tiers && addon.tiers?.length > 0 && (addon.subscribed || addon.inclusion_only)
    )

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData: BillingTableTierRow[] | undefined =
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
                                            projectedTotal: `$${parseFloat(
                                                tier.projected_amount_usd === 'None'
                                                    ? '0'
                                                    : tier.projected_amount_usd || '0'
                                            ).toFixed(2)}`,
                                        },
                                        ...(subscribedAddons?.map((addon) => {
                                            return {
                                                productName: addon.name,
                                                usage: compactNumber(addon.tiers?.[i]?.current_usage || 0),
                                                price: `$${addon.tiers?.[i]?.unit_amount_usd || '0.00'}`,
                                                total: `$${addon.tiers?.[i]?.current_amount_usd || '0.00'}`,
                                                projectedTotal: `$${parseFloat(
                                                    addon.tiers?.[i]?.projected_amount_usd === 'None'
                                                        ? '0'
                                                        : addon.tiers?.[i]?.projected_amount_usd || '0'
                                                ).toFixed(2)}`,
                                            }
                                        }) ?? []),
                                    ]
                                  : [],
                          columns: [
                              {
                                  title: '',
                                  dataIndex: 'icon',
                                  render: () => (
                                      <IconArrowRightDown className="transform -rotate-90 scale-x-[-1] text-base text-muted" />
                                  ),
                              },
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
                    <FeatureFlagUsageNotice product={product} />
                    <LemonBanner type="warning" className="text-sm pt-2">
                        Tier breakdowns are updated once daily and may differ from the gauge above.
                    </LemonBanner>
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
