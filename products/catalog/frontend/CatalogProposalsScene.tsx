import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AcceptRateBanner } from './AcceptRateBanner'
import { CatalogPageTabs } from './CatalogPageTabs'
import { ProposalCategoryRail } from './ProposalCategoryRail'
import { ProposalDetail } from './ProposalDetail'
import { ProposalListItem } from './ProposalListItem'
import { catalogProposalsLogic } from './catalogProposalsLogic'
import { PROPOSAL_CATEGORIES } from './proposalTypes'

export const scene: SceneExport = {
    component: CatalogProposalsScene,
    logic: catalogProposalsLogic,
}

export function CatalogProposalsScene(): JSX.Element {
    const { visibleProposals, selectedProposal, activeCategory } = useValues(catalogProposalsLogic)
    const { setSelectedProposalId, approveProposal } = useActions(catalogProposalsLogic)

    useKeyboardNav()

    const activeCat = PROPOSAL_CATEGORIES.find((c) => c.key === activeCategory)
    const isRejectedView = activeCategory === 'rejected'

    return (
        <SceneContent>
            <SceneTitleSection
                name="Catalog"
                description="Review AI-generated proposals — new definitions, drift alerts, duplicates and schema sync — before they reach your semantic layer."
                resourceType={{ type: 'data_warehouse' }}
            />
            <CatalogPageTabs activeTab="proposals" />

            <LemonBanner type="info" className="text-sm">
                <strong>Prototype.</strong> Mock data, no backend. Click around the categories, approve, reject (with a
                reason), snooze, and toggle the <em>Code</em> view on the right to see the YAML representation MCP/CLI
                would emit.
            </LemonBanner>

            <AcceptRateBanner />

            <div className="flex gap-4 min-h-[640px] items-stretch">
                <ProposalCategoryRail />

                <div className="flex flex-col gap-2 w-96 shrink-0">
                    <div className="px-1">
                        <div className="text-sm font-medium">
                            {isRejectedView ? 'Recently rejected' : activeCat?.label}
                        </div>
                        <div className="text-xs text-muted-alt">
                            {isRejectedView ? 'Audit trail of rejected proposals.' : activeCat?.description}
                        </div>
                    </div>
                    <div className="flex flex-col gap-2 overflow-y-auto pr-1">
                        {visibleProposals.length === 0 ? (
                            <div className="text-sm text-muted-alt p-4 border rounded bg-surface-primary text-center">
                                Nothing here.
                            </div>
                        ) : (
                            visibleProposals.map((p) => (
                                <ProposalListItem
                                    key={p.id}
                                    proposal={p}
                                    selected={selectedProposal?.id === p.id}
                                    onClick={() => setSelectedProposalId(p.id)}
                                />
                            ))
                        )}
                    </div>
                    {!isRejectedView && visibleProposals.length > 1 && activeCategory === 'metadata' ? (
                        <button
                            type="button"
                            className="text-xs px-2 py-1.5 border border-dashed rounded text-muted-alt hover:bg-fill-highlight-50"
                            onClick={() => visibleProposals.forEach((p) => approveProposal(p.id))}
                        >
                            Approve all {visibleProposals.length} metadata proposals
                        </button>
                    ) : null}
                </div>

                <div className="flex-1 min-w-0 flex flex-col border rounded bg-surface-primary p-4">
                    <ProposalDetail proposal={selectedProposal} />
                </div>
            </div>
        </SceneContent>
    )
}

function useKeyboardNav(): void {
    const { visibleProposals, selectedProposal } = useValues(catalogProposalsLogic)
    const { setSelectedProposalId, approveProposal } = useActions(catalogProposalsLogic)

    useEffect(() => {
        function onKey(e: KeyboardEvent): void {
            const target = e.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            if (visibleProposals.length === 0) {
                return
            }
            const idx = selectedProposal ? visibleProposals.findIndex((p) => p.id === selectedProposal.id) : -1
            if (e.key === 'j' || e.key === 'ArrowDown') {
                e.preventDefault()
                const next = visibleProposals[Math.min(idx + 1, visibleProposals.length - 1)]
                if (next) {setSelectedProposalId(next.id)}
            } else if (e.key === 'k' || e.key === 'ArrowUp') {
                e.preventDefault()
                const prev = visibleProposals[Math.max(idx - 1, 0)]
                if (prev) {setSelectedProposalId(prev.id)}
            } else if (e.key === 'a' && selectedProposal && selectedProposal.status === 'open') {
                e.preventDefault()
                approveProposal(selectedProposal.id)
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [visibleProposals, selectedProposal, setSelectedProposalId, approveProposal])
}
