import { Text } from '@posthog/quill'

import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'

const FEATURES = [
    { title: 'SQL editor and models', body: 'Write SQL and save it as models you can reuse.' },
    { title: 'Connect your tools', body: 'Connect the Trino CLI, Python, dbt, Metabase or Hex.' },
    { title: 'Data landing', body: 'Check that your events, persons and source tables have landed.' },
    {
        title: 'Usage, queries and storage',
        body: 'See what your warehouse uses, review its queries and check its storage.',
    },
    { title: 'Logins and access', body: 'Manage the logins that connect tools to your warehouse.' },
]

export function WarehouseExplainerFeatures(): JSX.Element {
    return (
        <WarehouseSection title="What you get" data-attr="warehouse-explainer-features">
            <ul className="m-0 grid list-none gap-3 p-0 @xl/warehouse-home:grid-cols-2 @4xl/warehouse-home:grid-cols-3">
                {FEATURES.map((feature) => (
                    <li key={feature.title} className="flex min-w-0 flex-col gap-0.5">
                        <Text size="sm" weight="semibold" render={<span />}>
                            {feature.title}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />}>
                            {feature.body}
                        </Text>
                    </li>
                ))}
            </ul>
        </WarehouseSection>
    )
}
