import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

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
        <details className="min-w-0 text-xs" data-attr="bi-source-context">
            <summary className="cursor-pointer">
                <span className="mr-1">Catalog details</span>
                <TableCertificationTag certification={table.certification} />
            </summary>
            <div
                className="flex max-h-48 flex-col gap-2 overflow-y-auto overscroll-contain py-2"
                role="region"
                aria-label="Catalog details"
                tabIndex={0}
            >
                {description && <p className="m-0 break-words text-secondary">{description}</p>}
                {table.certification?.notes && <p className="m-0 break-words">{table.certification.notes}</p>}
                <LemonButton
                    size="xsmall"
                    sideIcon={<IconExternal />}
                    to={`${urls.dataCatalog('certifications')}&table=${encodeURIComponent(table.name)}`}
                    onClick={() => captureBIWorksheetAction('catalog_source_opened', config)}
                >
                    View catalog details
                </LemonButton>
                <div className="flex flex-col gap-2">
                    <span className="font-semibold">Relationships and review status</span>
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
                                    {proposal.status === 'proposed'
                                        ? 'Awaiting review'
                                        : proposal.status === 'accepted'
                                          ? 'Accepted'
                                          : 'Rejected'}
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
                    <LemonButton size="xsmall" sideIcon={<IconExternal />} to={catalog}>
                        Review in catalog
                    </LemonButton>
                </div>
                <LemonButton
                    size="xsmall"
                    sideIcon={<IconExternal />}
                    to={`${catalog}&propose_table=${encodeURIComponent(table.name)}`}
                    onClick={() => captureBIWorksheetAction('catalog_relationship_requested', config)}
                >
                    Propose a relationship
                </LemonButton>
            </div>
        </details>
    )
}
