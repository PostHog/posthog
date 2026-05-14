// Types for the AI proposals inbox.
//
// Every shape here mirrors a real backend state in the catalog product:
// - "node_proposed" → CatalogNode.status = proposed (any kind — warehouse_table,
//   saved_query, system_table, posthog_table, metric, event_definition,
//   property_definition)
// - "node_drift"    → CatalogNode.status = drift
// - "relationship_proposed" → CatalogRelationship.status = proposed
//
// No invented proposal types — if the backend doesn't model it, it isn't here.

import type {
    CatalogNodeDTOApi,
    CatalogRelationshipDTOApi,
    MetricDefinitionSchemaApi,
} from 'products/catalog/frontend/generated/api.schemas'

export type ProposalKind = 'node_proposed' | 'node_drift' | 'relationship_proposed'

export interface NodeProposal {
    kind: 'node_proposed' | 'node_drift'
    id: string
    node: CatalogNodeDTOApi
    /** Present when node.kind === 'metric'. Looked up from the metrics endpoint. */
    metricDefinition?: MetricDefinitionSchemaApi
}

export interface RelationshipProposal {
    kind: 'relationship_proposed'
    id: string
    relationship: CatalogRelationshipDTOApi
    sourceNode: CatalogNodeDTOApi | null
    targetNode: CatalogNodeDTOApi | null
}

export type Proposal = NodeProposal | RelationshipProposal

export type CategoryKey = 'all' | 'node_proposed' | 'node_drift' | 'relationship_proposed' | 'rejected_relationships'

export interface ProposalCategory {
    key: CategoryKey
    label: string
    iconLabel: string
    description: string
}

export const PROPOSAL_CATEGORIES: ProposalCategory[] = [
    { key: 'all', label: 'Inbox', iconLabel: '∗', description: 'Everything waiting on review' },
    {
        key: 'node_proposed',
        label: 'New definitions',
        iconLabel: '⊕',
        description: 'Tables, saved queries, metrics, and event/property definitions the agent proposed',
    },
    {
        key: 'node_drift',
        label: 'Drift',
        iconLabel: '⚠',
        description: 'Definitions the agent flagged as stale after upstream changes',
    },
    {
        key: 'relationship_proposed',
        label: 'Relationships',
        iconLabel: '↔',
        description: 'Joins and dependencies between catalog nodes the agent proposed',
    },
]

export const KIND_LABELS: Record<ProposalKind, string> = {
    node_proposed: 'New definition',
    node_drift: 'Drift alert',
    relationship_proposed: 'Relationship',
}

/** Pretty label for a CatalogNode.kind. */
export const NODE_KIND_LABELS: Record<string, string> = {
    warehouse_table: 'Warehouse table',
    saved_query: 'Saved query',
    system_table: 'System table',
    posthog_table: 'PostHog table',
    metric: 'Metric',
    event_definition: 'Event definition',
    property_definition: 'Property definition',
}

/** Pretty label for a CatalogRelationship.kind. */
export const RELATIONSHIP_KIND_LABELS: Record<string, string> = {
    foreign_key: 'Foreign key',
    same_entity: 'Same entity',
    lineage: 'Lineage',
    declared_join: 'Declared join',
    join_candidate: 'Join candidate',
    depends_on: 'Depends on',
}
