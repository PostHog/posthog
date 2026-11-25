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

/** The pages that work without a warehouse. */
export function WarehouseExplainerAvailable(): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1">
            <Text size="xs" variant="muted" render={<span />}>
                Works without a warehouse
            </Text>
            {LINKS.map((link) => (
                <WarehouseExplainerLink key={link.target} to={link.to} target={link.target}>
                    {link.label}
                </WarehouseExplainerLink>
            ))}
        </div>
    )
}
