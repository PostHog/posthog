import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    catalogMetricsList,
    catalogNodesGraphRetrieve,
    catalogNodesPartialUpdate,
    catalogRelationshipsPartialUpdate,
} from 'products/catalog/frontend/generated/api'
import type {
    CatalogGraphDTOApi,
    CatalogMetricDTOApi,
    CatalogNodeDTOApi,
    CatalogRelationshipDTOApi,
    MetricDefinitionSchemaApi,
} from 'products/catalog/frontend/generated/api.schemas'

import type { catalogProposalsLogicType } from './catalogProposalsLogicType'
import { CategoryKey, NodeProposal, Proposal, RelationshipProposal } from './proposalTypes'

export type DetailViewMode = 'visual' | 'code'

const METRIC_PAGE_SIZE = 200

export const catalogProposalsLogic = kea<catalogProposalsLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogProposalsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setSelectedProposalId: (id: string | null) => ({ id }),
        setActiveCategory: (category: CategoryKey) => ({ category }),
        setDetailViewMode: (mode: DetailViewMode) => ({ mode }),
        approveProposal: (proposal: Proposal) => ({ proposal }),
        markOfficial: (proposal: NodeProposal) => ({ proposal }),
        rejectProposal: (proposal: RelationshipProposal, reason: string) => ({ proposal, reason }),
        markStale: (proposal: RelationshipProposal) => ({ proposal }),
        replaceNode: (node: CatalogNodeDTOApi) => ({ node }),
        replaceRelationship: (relationship: CatalogRelationshipDTOApi) => ({ relationship }),
    }),

    loaders(({ values }) => ({
        graph: [
            null as CatalogGraphDTOApi | null,
            {
                loadGraph: async () => {
                    return await catalogNodesGraphRetrieve(String(values.currentProjectId))
                },
            },
        ],
        metrics: [
            [] as CatalogMetricDTOApi[],
            {
                // Walk all pages so the inbox detail can show the metric definition
                // alongside the bound CatalogNode.
                loadMetrics: async () => {
                    const projectId = String(values.currentProjectId)
                    const all: CatalogMetricDTOApi[] = []
                    for (let offset = 0; ; offset += METRIC_PAGE_SIZE) {
                        const page = await catalogMetricsList(projectId, { limit: METRIC_PAGE_SIZE, offset })
                        all.push(...page.results)
                        if (!page.next || page.results.length < METRIC_PAGE_SIZE) {
                            break
                        }
                    }
                    return all
                },
            },
        ],
    })),

    reducers({
        activeCategory: [
            'all' as CategoryKey,
            {
                setActiveCategory: (_, { category }) => category,
            },
        ],
        selectedProposalId: [
            null as string | null,
            {
                setSelectedProposalId: (_, { id }) => id,
                setActiveCategory: () => null,
            },
        ],
        detailViewMode: [
            'visual' as DetailViewMode,
            {
                setDetailViewMode: (_, { mode }) => mode,
            },
        ],
        // Splice updated rows back into the graph payload so the inbox reflects
        // PATCH responses without re-fetching the whole graph.
        graph: {
            replaceNode: (state, { node }) =>
                state ? { ...state, nodes: state.nodes.map((n) => (n.id === node.id ? node : n)) } : state,
            replaceRelationship: (state, { relationship }) =>
                state
                    ? {
                          ...state,
                          relationships: state.relationships.map((r) => (r.id === relationship.id ? relationship : r)),
                      }
                    : state,
        },
    }),

    selectors({
        metricDefinitionByNodeId: [
            (s) => [s.metrics],
            (metrics): Record<string, MetricDefinitionSchemaApi> => {
                const map: Record<string, MetricDefinitionSchemaApi> = {}
                for (const m of metrics) {
                    map[m.node.id] = m.definition
                }
                return map
            },
        ],
        nodesById: [
            (s) => [s.graph],
            (graph): Record<string, CatalogNodeDTOApi> => {
                const map: Record<string, CatalogNodeDTOApi> = {}
                if (!graph) {
                    return map
                }
                for (const n of graph.nodes) {
                    map[n.id] = n
                }
                return map
            },
        ],
        proposals: [
            (s) => [s.graph, s.metricDefinitionByNodeId, s.nodesById],
            (graph, metricMap, nodesById): Proposal[] => {
                if (!graph) {
                    return []
                }
                const out: Proposal[] = []
                for (const node of graph.nodes) {
                    if (node.status === 'proposed' || node.status === 'drift') {
                        out.push({
                            kind: node.status === 'proposed' ? 'node_proposed' : 'node_drift',
                            id: `node:${node.id}`,
                            node,
                            metricDefinition: node.kind === 'metric' ? metricMap[node.id] : undefined,
                        })
                    }
                }
                for (const rel of graph.relationships) {
                    if (rel.status === 'proposed' || rel.status === 'rejected') {
                        out.push({
                            kind: 'relationship_proposed',
                            id: `relationship:${rel.id}`,
                            relationship: rel,
                            sourceNode: nodesById[rel.source_node_id] ?? null,
                            targetNode: nodesById[rel.target_node_id] ?? null,
                        })
                    }
                }
                return out
            },
        ],
        categoryCounts: [
            (s) => [s.proposals],
            (proposals): Record<CategoryKey, number> => {
                const counts: Record<CategoryKey, number> = {
                    all: 0,
                    node_proposed: 0,
                    node_metric: 0,
                    node_drift: 0,
                    relationship_proposed: 0,
                    rejected_relationships: 0,
                }
                for (const p of proposals) {
                    if (p.kind === 'relationship_proposed') {
                        if (p.relationship.status === 'proposed') {
                            counts.all += 1
                            counts.relationship_proposed += 1
                        } else if (p.relationship.status === 'rejected') {
                            counts.rejected_relationships += 1
                        }
                    } else {
                        counts.all += 1
                        counts[p.kind] += 1
                        if (p.kind === 'node_proposed' && p.node.kind === 'metric') {
                            counts.node_metric += 1
                        }
                    }
                }
                return counts
            },
        ],
        visibleProposals: [
            (s) => [s.proposals, s.activeCategory],
            (proposals, category): Proposal[] => {
                if (category === 'rejected_relationships') {
                    return proposals.filter(
                        (p) => p.kind === 'relationship_proposed' && p.relationship.status === 'rejected'
                    )
                }
                const open = proposals.filter((p) =>
                    p.kind === 'relationship_proposed' ? p.relationship.status === 'proposed' : true
                )
                if (category === 'all') {
                    return open
                }
                if (category === 'node_metric') {
                    return open.filter((p) => p.kind === 'node_proposed' && p.node.kind === 'metric')
                }
                return open.filter((p) => p.kind === category)
            },
        ],
        selectedProposal: [
            (s) => [s.proposals, s.visibleProposals, s.selectedProposalId],
            (proposals, visible, id): Proposal | null => {
                if (id) {
                    return proposals.find((p) => p.id === id) ?? null
                }
                return visible[0] ?? null
            },
        ],
        isLoading: [(s) => [s.graphLoading, s.metricsLoading], (graph, metrics): boolean => Boolean(graph || metrics)],
    }),

    listeners(({ values, actions }) => ({
        approveProposal: async ({ proposal }) => {
            const projectId = String(values.currentProjectId)
            try {
                if (proposal.kind === 'relationship_proposed') {
                    const updated = await catalogRelationshipsPartialUpdate(projectId, proposal.relationship.id, {
                        status: 'accepted',
                    })
                    actions.replaceRelationship(updated)
                    lemonToast.success('Relationship accepted')
                } else {
                    const updated = await catalogNodesPartialUpdate(projectId, proposal.node.id, {
                        status: 'approved',
                    })
                    actions.replaceNode(updated)
                    lemonToast.success(proposal.kind === 'node_drift' ? 'Drift acknowledged' : 'Definition approved')
                }
            } catch (error) {
                lemonToast.error(`Failed to approve: ${(error as Error).message}`)
            }
        },
        markOfficial: async ({ proposal }) => {
            const projectId = String(values.currentProjectId)
            try {
                const updated = await catalogNodesPartialUpdate(projectId, proposal.node.id, {
                    status: 'official',
                })
                actions.replaceNode(updated)
                lemonToast.success('Marked official')
            } catch (error) {
                lemonToast.error(`Failed to mark official: ${(error as Error).message}`)
            }
        },
        rejectProposal: async ({ proposal, reason }) => {
            const projectId = String(values.currentProjectId)
            try {
                const updated = await catalogRelationshipsPartialUpdate(projectId, proposal.relationship.id, {
                    status: 'rejected',
                    reasoning: reason || proposal.relationship.reasoning,
                })
                actions.replaceRelationship(updated)
                lemonToast.success('Relationship rejected')
            } catch (error) {
                lemonToast.error(`Failed to reject: ${(error as Error).message}`)
            }
        },
        markStale: async ({ proposal }) => {
            const projectId = String(values.currentProjectId)
            try {
                const updated = await catalogRelationshipsPartialUpdate(projectId, proposal.relationship.id, {
                    status: 'stale',
                })
                actions.replaceRelationship(updated)
                lemonToast.success('Relationship marked stale')
            } catch (error) {
                lemonToast.error(`Failed to mark stale: ${(error as Error).message}`)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadGraph()
        actions.loadMetrics()
    }),
])
