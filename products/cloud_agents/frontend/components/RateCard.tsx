import { useValues } from 'kea'

import { LemonCard, LemonTable } from '@posthog/lemon-ui'

import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'
import { formatRate } from '../utils/pricing'

/** The two compute rates and the hourly price of each box size, as the catalog returns them. */
export function RateCard(): JSX.Element {
    const { sizes, rates, catalogLoading } = useValues(cloudAgentsCatalogLogic)

    return (
        <LemonCard hoverEffect={false} className="flex min-w-0 flex-col gap-3 p-4" data-attr="cloud-agents-rate-card">
            <div>
                <h3 className="m-0 text-base font-semibold">Rate card</h3>
                <p className="m-0 text-secondary text-xs">
                    Compute is billed per second on the box size that you select. Model usage is billed separately: in
                    AI credits when PostHog provides the model, or against your own subscription when you bring one.
                </p>
            </div>
            {rates && (
                <div className="flex flex-wrap gap-x-6 gap-y-1" translate="no">
                    <span>
                        <span className="font-semibold tabular-nums">{formatRate(rates.vcpu_hour_usd)}</span> per
                        vCPU-hour
                    </span>
                    <span>
                        <span className="font-semibold tabular-nums">{formatRate(rates.memory_gib_hour_usd)}</span> per
                        GiB-hour
                    </span>
                </div>
            )}
            <LemonTable
                size="small"
                dataSource={sizes}
                rowKey="name"
                loading={catalogLoading}
                columns={[
                    { title: 'Box size', key: 'name', render: (_, size) => <span translate="no">{size.name}</span> },
                    { title: 'vCPU', key: 'vcpu', align: 'right', render: (_, size) => size.vcpu },
                    { title: 'Memory', key: 'memory', align: 'right', render: (_, size) => `${size.memory_gib} GiB` },
                    {
                        title: 'Price per hour',
                        key: 'price',
                        align: 'right',
                        render: (_, size) => (
                            <span className="font-semibold tabular-nums">{formatRate(size.price_per_hour_usd)}</span>
                        ),
                    },
                ]}
            />
        </LemonCard>
    )
}
