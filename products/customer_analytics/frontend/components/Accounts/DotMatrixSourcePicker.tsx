import { useValues } from 'kea'

import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { DotMatrixTileSource } from './dotMatrixTileConfig'

export function DotMatrixSourcePicker({
    value,
    onChange,
    id,
}: {
    value: DotMatrixTileSource['kind'] | null
    onChange: (kind: DotMatrixTileSource['kind'] | null) => void
    id: string
}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel htmlFor={id}>Data source</LemonLabel>
            <LemonSelect
                id={id}
                value={value}
                onSelect={onChange}
                fullWidth
                placeholder="Choose a data source"
                data-attr="account-dot-matrix-source"
                options={[
                    {
                        value: 'usage_metrics',
                        label: 'Customer usage',
                        tooltip: 'Usage metrics for each person, by week.',
                    },
                    ...(featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_PRODUCT_USAGE]
                        ? [
                              {
                                  value: 'product_usage' as const,
                                  label: 'Product usage',
                                  tooltip: 'PostHog products used by this account, by week.',
                              },
                          ]
                        : []),
                    { value: 'hogql', label: 'Custom HogQL', tooltip: 'Run SQL and map its result columns.' },
                ]}
            />
        </div>
    )
}
