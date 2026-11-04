import { LemonLabel, LemonSelect } from '@posthog/lemon-ui'

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
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel htmlFor={id}>Data source</LemonLabel>
            <LemonSelect
                id={id}
                value={value}
                onChange={onChange}
                fullWidth
                placeholder="Choose a data source"
                data-attr="account-dot-matrix-source"
                options={[
                    {
                        value: 'usage_metrics',
                        label: 'Account activity',
                        tooltip: 'Usage metrics for each person, by week.',
                    },
                    {
                        value: 'product_usage',
                        label: 'Product usage',
                        tooltip: 'PostHog products used by this account, by week.',
                    },
                    { value: 'hogql', label: 'Custom HogQL', tooltip: 'Run SQL and map its result columns.' },
                ]}
            />
        </div>
    )
}
