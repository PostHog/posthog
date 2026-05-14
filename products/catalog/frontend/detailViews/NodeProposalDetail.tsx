import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import type { CatalogColumnDTOApi, MetricDefinitionSchemaApi } from 'products/catalog/frontend/generated/api.schemas'

import { NodeProposal, NODE_KIND_LABELS } from '../proposalTypes'

/**
 * Detail view for a CatalogNode proposal — covers both `status=proposed` and
 * `status=drift` since they share the same shape. For metric-kind nodes,
 * additionally renders the bound CatalogMetric.definition.
 */
export function NodeProposalDetail({ proposal }: { proposal: NodeProposal }): JSX.Element {
    const { node } = proposal
    const kindLabel = NODE_KIND_LABELS[node.kind] ?? node.kind

    return (
        <div className="flex flex-col gap-4">
            {proposal.kind === 'node_drift' ? (
                <LemonBanner type="warning" className="text-sm">
                    <span className="font-medium">Drift detected.</span> The agent flagged this definition as stale
                    after upstream changes.{' '}
                    {node.last_traversed_at ? `Last traversed ${node.last_traversed_at}.` : null}
                </LemonBanner>
            ) : null}

            <section className="border rounded p-4 bg-surface-primary">
                <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="font-mono text-base">{node.name}</span>
                    <LemonTag type="primary" size="small">
                        {kindLabel}
                    </LemonTag>
                    {node.business_domain ? (
                        <LemonTag type="option" size="small">
                            domain: {node.business_domain}
                        </LemonTag>
                    ) : null}
                    {node.semantic_role ? <LemonTag size="small">role: {node.semantic_role}</LemonTag> : null}
                </div>
                <p className="text-sm text-default">
                    {node.description ?? (
                        <span className="italic text-muted-alt">
                            Agent hasn't described this yet — approving will leave the description blank.
                        </span>
                    )}
                </p>
                {node.tags.length ? (
                    <div className="flex flex-wrap gap-1 mt-3">
                        {node.tags.map((t) => (
                            <LemonTag key={t} size="small">
                                {t}
                            </LemonTag>
                        ))}
                    </div>
                ) : null}
            </section>

            {node.kind === 'metric' && proposal.metricDefinition ? (
                <MetricDefinitionSection definition={proposal.metricDefinition} />
            ) : null}

            {node.columns.length ? <ColumnsSection columns={node.columns} /> : null}
        </div>
    )
}

function MetricDefinitionSection({ definition }: { definition: MetricDefinitionSchemaApi }): JSX.Element {
    return (
        <section>
            <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-1">Metric definition</h4>
            <pre className="text-xs bg-bg-3000 border rounded p-3 overflow-x-auto whitespace-pre">
                {JSON.stringify(definition, null, 2)}
            </pre>
        </section>
    )
}

function ColumnsSection({ columns }: { columns: CatalogColumnDTOApi[] }): JSX.Element {
    return (
        <section>
            <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Columns ({columns.length})</h4>
            <div className="flex flex-col gap-1">
                {columns.map((c) => (
                    <div
                        key={c.id}
                        className="flex items-center gap-2 px-3 py-1.5 text-xs border rounded bg-surface-primary"
                    >
                        <span className="font-mono">{c.name}</span>
                        {c.hogql_type ? <span className="font-mono text-muted-alt">{c.hogql_type}</span> : null}
                        <div className="ml-auto flex items-center gap-1">
                            {c.semantic_type ? (
                                <LemonTag type="option" size="small">
                                    {c.semantic_type.replace('_', ' ')}
                                </LemonTag>
                            ) : null}
                            {c.pii_class && c.pii_class !== 'unknown' ? (
                                <LemonTag
                                    type={
                                        c.pii_class === 'pii'
                                            ? 'danger'
                                            : c.pii_class === 'sensitive'
                                              ? 'warning'
                                              : 'default'
                                    }
                                    size="small"
                                >
                                    {c.pii_class}
                                </LemonTag>
                            ) : null}
                        </div>
                    </div>
                ))}
            </div>
        </section>
    )
}
