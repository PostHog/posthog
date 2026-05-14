import { actions, kea, path, reducers, selectors } from 'kea'

import { MOCK_PROPOSALS } from './proposalsMockData'
import { Proposal, ProposalKind, ProposalStatus } from './proposalTypes'
import type { catalogProposalsLogicType } from './catalogProposalsLogicType'

export type CategoryKey = ProposalKind | 'all' | 'rejected'

export type DetailViewMode = 'visual' | 'code'

interface ProposalStateOverrides {
    status?: ProposalStatus
    rejectionReason?: string
}

export const catalogProposalsLogic = kea<catalogProposalsLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogProposalsLogic']),
    actions({
        setSelectedProposalId: (id: string | null) => ({ id }),
        setActiveCategory: (category: CategoryKey) => ({ category }),
        approveProposal: (id: string) => ({ id }),
        rejectProposal: (id: string, reason: string) => ({ id, reason }),
        snoozeProposal: (id: string) => ({ id }),
        setDetailViewMode: (mode: DetailViewMode) => ({ mode }),
    }),
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
        proposalOverrides: [
            {} as Record<string, ProposalStateOverrides>,
            {
                approveProposal: (state, { id }) => ({
                    ...state,
                    [id]: { status: 'approved' },
                }),
                rejectProposal: (state, { id, reason }) => ({
                    ...state,
                    [id]: { status: 'rejected', rejectionReason: reason },
                }),
                snoozeProposal: (state, { id }) => ({
                    ...state,
                    [id]: { status: 'snoozed' },
                }),
            },
        ],
        detailViewMode: [
            'visual' as DetailViewMode,
            {
                setDetailViewMode: (_, { mode }) => mode,
            },
        ],
    }),
    selectors({
        proposals: [
            (s) => [s.proposalOverrides],
            (overrides): Proposal[] =>
                MOCK_PROPOSALS.map((p) => {
                    const o = overrides[p.id]
                    if (!o) {
                        return p
                    }
                    return {
                        ...p,
                        status: o.status ?? p.status,
                        rejectionReason: o.rejectionReason ?? p.rejectionReason,
                    }
                }),
        ],
        categoryCounts: [
            (s) => [s.proposals],
            (proposals): Record<CategoryKey, number> => {
                const counts: Record<string, number> = {
                    all: 0,
                    rejected: 0,
                }
                for (const p of proposals) {
                    if (p.status === 'open') {
                        counts.all = (counts.all ?? 0) + 1
                        counts[p.kind] = (counts[p.kind] ?? 0) + 1
                    } else if (p.status === 'rejected') {
                        counts.rejected = (counts.rejected ?? 0) + 1
                    }
                }
                return counts as Record<CategoryKey, number>
            },
        ],
        visibleProposals: [
            (s) => [s.proposals, s.activeCategory],
            (proposals, category): Proposal[] => {
                if (category === 'rejected') {
                    return proposals.filter((p) => p.status === 'rejected')
                }
                const open = proposals.filter((p) => p.status === 'open')
                if (category === 'all') {
                    return open
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
    }),
])
