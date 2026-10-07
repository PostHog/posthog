import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { TableCertificationTag } from 'products/data_warehouse/frontend/shared/components/TableCertificationBadge'

import { captureBIWorksheetAction } from './biEditorAnalytics'
import { biEditorLogic } from './biEditorLogic'
import { biSourceContextLogic } from './biSourceContextLogic'

export function BISourceContext({ table }: { table: DatabaseSchemaTable }): JSX.Element {
    const { config } = useValues(biEditorLogic)
    const { description, relationships, relationshipsLoading, joins, contextError } = useValues(
        biSourceContextLogic({ table })
    )
    const { loadRelationships } = useActions(biSourceContextLogic({ table }))
    const catalog = `${urls.dataCatalog('relationships')}&table=${encodeURIComponent(table.name)}`
    return (
        <div className="flex min-w-0 flex-col gap-1 text-xs" data-attr="bi-source-context">
            <div>
                <TableCertificationTag certification={table.certification} />
            </div>
            {description && <p className="m-0 break-words text-secondary">{description}</p>}
            {table.certification?.notes && <p className="m-0 break-words">{table.certification.notes}</p>}
            <Link
                to={`${urls.dataCatalog('certifications')}&table=${encodeURIComponent(table.name)}`}
                onClick={() => captureBIWorksheetAction('catalog_source_opened', config)}
            >
                View catalog details
            </Link>
            <details>
                <summary className="cursor-pointer">Relationships and review status</summary>
                <div className="flex flex-col gap-2 py-2">
                    {joins.map((join) => (
                        <div key={join.id} className="break-words">
                            {join.source_table_name}.{join.source_table_key} → {join.joining_table_name}.
                            {join.joining_table_key}
                            <div className="text-secondary">Access with {join.field_name}</div>
                            <LemonTag type="success">Configured</LemonTag>
                        </div>
                    ))}
                    {relationships?.results.map((proposal) => (
                        <div key={proposal.id} className="break-words">
                            {proposal.source_table_name}.{proposal.source_table_key} → {proposal.joining_table_name}.
                            {proposal.joining_table_key}
                            <div>
                                <LemonTag
                                    type={
                                        proposal.status === 'accepted'
                                            ? 'success'
                                            : proposal.status === 'rejected'
                                              ? 'danger'
                                              : 'warning'
                                    }
                                >
                                    {proposal.status === 'proposed' ? 'Awaiting review' : proposal.status}
                                </LemonTag>
                            </div>
                            {proposal.reasoning && <div className="text-secondary">{proposal.reasoning}</div>}
                        </div>
                    ))}
                    {!relationshipsLoading && !contextError && !joins.length && !relationships?.results.length && (
                        <span>No configured or proposed relationships.</span>
                    )}
                    {contextError && <span>Could not load relationship reviews.</span>}
                    {(contextError || relationships?.hasMore) && (
                        <LemonButton size="xsmall" loading={relationshipsLoading} onClick={() => loadRelationships()}>
                            {contextError ? 'Retry' : 'Load more'}
                        </LemonButton>
                    )}
                    <Link to={catalog}>Review in catalog</Link>
                </div>
            </details>
            <LemonButton
                size="xsmall"
                to={`${catalog}&propose_table=${encodeURIComponent(table.name)}`}
                onClick={() => captureBIWorksheetAction('catalog_relationship_requested', config)}
            >
                Propose a relationship
            </LemonButton>
        </div>
    )
}
