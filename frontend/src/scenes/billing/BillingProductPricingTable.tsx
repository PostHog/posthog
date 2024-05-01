import { IconInfo } from '@posthog/icons'
import { LemonTable, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { compactNumber } from 'lib/utils'

import { BillingProductV2Type } from '~/types'

import { billingLogic } from './billingLogic'
import { getTierDescription } from './BillingProduct'

export const BillingProductPricingTable = ({
    product,
}: {
    product: BillingProductV2Type
    usageKey?: string
}): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const addonPriceColumns = product.addons
        // only get addons that are subscribed or were subscribed and have a projected amount
        ?.filter((addon) => addon.subscribed || parseFloat(addon.projected_amount_usd || ''))
        .map((addon) => ({
            title: `${addon.name} price`,
            dataIndex: `${addon.type}-price`,
        }))

    const tableColumns = [
        { title: `Priced per ${product.unit}`, dataIndex: 'volume' },
        { title: addonPriceColumns?.length > 0 ? 'Base price' : 'Price', dataIndex: 'basePrice' },
        ...(addonPriceColumns || []),
        { title: 'Current Usage', dataIndex: 'usage' },
        { title: 'Total', dataIndex: 'total' },
        { title: 'Projected Total', dataIndex: 'projectedTotal' },
    ]

    type TableTierDatum = {
        volume: string
        basePrice: string
        [addonPrice: string]: string
        usage: string
        total: string
        projectedTotal: string
    }

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData: TableTierDatum[] | undefined =
        product.tiers && product.tiers.length > 0
            ? product.tiers
                  ?.map((tier, i) => {
                      const addonPricesForTier = product.addons?.map((addon) => ({
                          [`${addon.type}-price`]: `${
                              addon.tiers?.[i]?.unit_amount_usd !== '0'
                                  ? '$' + addon.tiers?.[i]?.unit_amount_usd
                                  : 'Free'
                          }`,
                      }))
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
                          basePrice: tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free',
                          usage: compactNumber(tier.current_usage),
                          total: `$${totalForTier.toFixed(2) || '0.00'}`,
                          projectedTotal: `$${projectedTotalForTier.toFixed(2) || '0.00'}`,
                      }
                      // if there are any addon prices we need to include, put them in the table
                      addonPricesForTier?.map((addonPrice) => {
                          Object.assign(tierData, addonPrice)
                      })
                      return tierData
                  })
                  // Add a row at the end for the total
                  .concat({
                      volume: 'Total',
                      basePrice: '',
                      usage: '',
                      total: `$${product.current_amount_usd || '0.00'}`,
                      projectedTotal: `$${product.projected_amount_usd || '0.00'}`,
                  })
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
