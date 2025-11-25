import { useValues } from 'kea'

import { IconArrowRightDown, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'

import { compactNumber } from 'lib/utils'

import {
    BillingProductV2AddonType,
    BillingProductV2Type,
    BillingTableTierRow,
    ProductPricingTierSubrows,
} from '~/types'

import { getTierDescription } from './BillingProduct'
import { formatWithDecimals, isProductVariantPrimary } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

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
    product: BillingProductV2Type | BillingProductV2AddonType
    usageKey?: string
}): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { isProductWithVariants, projectedAmountExcludingAddons, currentAmountTotalActual } = useValues(
        billingProductLogic({ product })
    )

    const showProjectedTotalWithLimitTooltip =
        'addons' in product && product.projected_amount_usd_with_limit !== product.projected_amount_usd

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
        {
            title: showProjectedTotalWithLimitTooltip ? (
                <Tooltip title="The projected total for the product tiers and add-ons does not account for billing limits. To see the projected total that accounts for the billing limits, see the projected amount for the whole product above.">
                    <span>
                        Projected Total <IconInfo className="text-muted text-sm" />
                    </span>
                </Tooltip>
            ) : (
                'Projected Total'
            ),
            dataIndex: 'projectedTotal',
        },
    ]

    const subscribedAddons =
        'addons' in product
            ? product.addons?.filter(
                  (addon: BillingProductV2AddonType) =>
                      addon.tiers &&
                      addon.tiers?.length > 0 &&
                      (addon.subscribed || addon.inclusion_only) &&
                      // Exclude add-ons that are product variants since those are shown separately with their own table
                      !isProductWithVariants
              )
            : []

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
                                            price: `$${formatWithDecimals(parseFloat(tier.unit_amount_usd || '0'))}`,
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
                                                price: `$${formatWithDecimals(parseFloat(addon.tiers?.[i]?.unit_amount_usd || '0'))}`,
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
                                      <IconArrowRightDown className="transform -rotate-90 scale-x-[-1] text-base text-secondary" />
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
                      const totalForTier = isProductVariantPrimary(product.type)
                          ? parseFloat(tier.current_amount_usd || '0')
                          : parseFloat(tier.current_amount_usd || '') +
                            ('addons' in product
                                ? product.addons?.reduce(
                                      (acc: number, addon: BillingProductV2AddonType) =>
                                          acc + parseFloat(addon.tiers?.[i]?.current_amount_usd || ''),
                                      0
                                  ) || 0
                                : 0)
                      const projectedTotalForTier = isProductVariantPrimary(product.type)
                          ? parseFloat(tier.projected_amount_usd || '0')
                          : (parseFloat(tier.projected_amount_usd || '') || 0) +
                            ('addons' in product
                                ? product.addons?.reduce(
                                      (acc: number, addon: BillingProductV2AddonType) =>
                                          acc + (parseFloat(addon.tiers?.[i]?.projected_amount_usd || '') || 0),
                                      0
                                  ) || 0
                                : 0)

                      const tierData = {
                          volume: product.tiers // this is silly because we know there are tiers since we check above, but typescript doesn't
                              ? getTierDescription(product.tiers, i, product, billing?.billing_period?.interval || '')
                              : '',
                          basePrice:
                              tier.unit_amount_usd !== '0'
                                  ? `$${formatWithDecimals(parseFloat(tier.unit_amount_usd || '0'))}${
                                        product.type !== 'session_replay' && subscribedAddons?.length > 0
                                            ? ' + addons'
                                            : ''
                                    }`
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
                          total: `$${currentAmountTotalActual}`,
                          projectedTotal: isProductWithVariants
                              ? `$${projectedAmountExcludingAddons || '0.00'}`
                              : `$${product.projected_amount_usd || '0.00'}`,
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
                    <LemonBanner type="warning" className="text-sm pt-2 mt-2">
                        Tier breakdowns are updated once daily and may differ from the gauge above.
                    </LemonBanner>
                </>
            ) : parseFloat(product.unit_amount_usd || '0') > 0 ? (
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
            ) : null}
        </div>
    )
}
