import { Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { WarehouseExplainerLink } from './WarehouseExplainerLink'

// pinned: the targets are sent as a property of `warehouse explainer link clicked` and are part of each link's data-attr.
const LINKS = [
    { target: 'sql-editor', label: 'SQL editor', to: urls.sqlEditor() },
    { target: 'sources', label: 'Sources', to: urls.sources() },
    { target: 'models', label: 'Models', to: urls.models() },
    { target: 'data-catalog', label: 'Data catalog', to: urls.dataCatalog() },
]

export function WarehouseExplainerAvailable(): JSX.Element {
    return (
        <section aria-labelledby="warehouse-explainer-available" className="flex flex-col gap-1.5">
            <Text size="sm" weight="semibold" render={<h2 id="warehouse-explainer-available" className="m-0" />}>
                Available now
            </Text>
            <Text size="xs" variant="muted">
                These work without a managed warehouse.
            </Text>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
                {LINKS.map((link) => (
                    <WarehouseExplainerLink key={link.target} to={link.to} target={link.target}>
                        {link.label}
                    </WarehouseExplainerLink>
                ))}
            </div>
        </section>
    )
}
