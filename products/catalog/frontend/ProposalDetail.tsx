import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArchive, IconCheckCircle, IconStar, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSegmentedButton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { catalogProposalsLogic } from './catalogProposalsLogic'
import { NodeProposalDetail } from './detailViews/NodeProposalDetail'
import { RelationshipDetail } from './detailViews/RelationshipDetail'
import { KIND_LABELS, NODE_KIND_LABELS, Proposal, RELATIONSHIP_KIND_LABELS } from './proposalTypes'

interface ProposalDetailProps {
    proposal: Proposal | null
}

export function ProposalDetail({ proposal }: ProposalDetailProps): JSX.Element {
    const { detailViewMode } = useValues(catalogProposalsLogic)
    const { setDetailViewMode, approveProposal, markOfficial, rejectProposal, markStale } =
        useActions(catalogProposalsLogic)
    const [rejectMode, setRejectMode] = useState(false)
    const [rejectReason, setRejectReason] = useState('')

    if (!proposal) {
        return (
            <div className="flex flex-col items-center justify-center text-muted-alt p-8 flex-1">
                <span className="text-4xl mb-2" aria-hidden>
                    ✓
                </span>
                <div className="font-medium">All clear</div>
                <div className="text-sm">Nothing waiting in this category.</div>
            </div>
        )
    }

    const { title, summary, confidence, status } = describe(proposal)
    const isRelationship = proposal.kind === 'relationship_proposed'
    const isClosed = isRelationship && proposal.relationship.status !== 'proposed'

    return (
        <div className="flex flex-col flex-1 min-h-0 min-w-0">
            {/* Fixed header */}
            <header className="flex flex-col gap-2 px-4 pt-4 pb-3 border-b shrink-0">
                <div className="flex items-center gap-2 flex-wrap">
                    <LemonTag type="primary" size="small">
                        {KIND_LABELS[proposal.kind]}
                    </LemonTag>
                    <StatusTag status={status} />
                    {confidence != null ? (
                        <span className="text-xs text-muted-alt tabular-nums">
                            {Math.round(confidence * 100)}% confidence
                        </span>
                    ) : null}
                    <div className="ml-auto">
                        <LemonSegmentedButton
                            size="xsmall"
                            value={detailViewMode}
                            onChange={(v) => setDetailViewMode(v)}
                            options={[
                                { value: 'visual', label: 'Visual' },
                                { value: 'code', label: 'Code' },
                            ]}
                        />
                    </div>
                </div>
                <h2 className="text-lg font-semibold leading-snug">{title}</h2>
                <p className="text-sm text-muted-alt">{summary}</p>
            </header>

            {/* Scrollable body — only this region scrolls, header and footer stay put */}
            <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4 flex flex-col gap-4">
                {detailViewMode === 'code' ? (
                    <CodeView proposal={proposal} />
                ) : (
                    <>
                        <ProposalBody proposal={proposal} />
                        <LemonDivider className="my-0" />
                        <WhySection proposal={proposal} />
                    </>
                )}
            </div>

            {/* Pinned footer */}
            {!isClosed ? (
                <footer className="flex flex-col gap-2 px-4 py-3 border-t shrink-0 bg-surface-primary">
                    {rejectMode && isRelationship ? (
                        <div className="flex flex-col gap-2">
                            <LemonTextArea
                                value={rejectReason}
                                onChange={setRejectReason}
                                placeholder="Why are you rejecting? The reasoning is stored on the relationship for audit."
                                minRows={2}
                                maxRows={4}
                            />
                            <div className="flex items-center gap-2">
                                <LemonButton
                                    type="primary"
                                    status="danger"
                                    onClick={() => {
                                        rejectProposal(proposal, rejectReason.trim())
                                        setRejectReason('')
                                        setRejectMode(false)
                                    }}
                                >
                                    Confirm reject
                                </LemonButton>
                                <LemonButton onClick={() => setRejectMode(false)}>Cancel</LemonButton>
                            </div>
                        </div>
                    ) : (
                        <ActionBar
                            proposal={proposal}
                            onApprove={() => approveProposal(proposal)}
                            onMarkOfficial={() => {
                                if (proposal.kind !== 'relationship_proposed') {
                                    markOfficial(proposal)
                                }
                            }}
                            onMarkStale={() => {
                                if (proposal.kind === 'relationship_proposed') {
                                    markStale(proposal)
                                }
                            }}
                            onOpenReject={() => setRejectMode(true)}
                        />
                    )}
                </footer>
            ) : null}
        </div>
    )
}

function describe(proposal: Proposal): {
    title: string
    summary: string
    confidence: number | null
    status: string
} {
    if (proposal.kind === 'relationship_proposed') {
        const { relationship, sourceNode, targetNode } = proposal
        return {
            title: `${sourceNode?.name ?? '?'} ↔ ${targetNode?.name ?? '?'}`,
            summary:
                RELATIONSHIP_KIND_LABELS[relationship.kind] +
                (relationship.reasoning ? ` · ${relationship.reasoning}` : ''),
            confidence: relationship.confidence,
            status: relationship.status,
        }
    }
    const { node } = proposal
    return {
        title: node.name,
        summary: NODE_KIND_LABELS[node.kind] ?? node.kind,
        confidence: node.confidence,
        status: node.status,
    }
}

function StatusTag({ status }: { status: string }): JSX.Element | null {
    if (status === 'approved') {
        return (
            <LemonTag type="success" size="small">
                Approved
            </LemonTag>
        )
    }
    if (status === 'official') {
        return (
            <LemonTag type="success" size="small">
                Official
            </LemonTag>
        )
    }
    if (status === 'rejected') {
        return (
            <LemonTag type="danger" size="small">
                Rejected
            </LemonTag>
        )
    }
    if (status === 'stale') {
        return (
            <LemonTag type="warning" size="small">
                Stale
            </LemonTag>
        )
    }
    if (status === 'drift') {
        return (
            <LemonTag type="warning" size="small">
                Drift
            </LemonTag>
        )
    }
    return null
}

function ProposalBody({ proposal }: { proposal: Proposal }): JSX.Element {
    if (proposal.kind === 'relationship_proposed') {
        return <RelationshipDetail proposal={proposal} />
    }
    return <NodeProposalDetail proposal={proposal} />
}

function WhySection({ proposal }: { proposal: Proposal }): JSX.Element {
    const items: { source: string; detail: string | null }[] = []
    if (proposal.kind === 'relationship_proposed') {
        const r = proposal.relationship
        items.push({ source: 'agent', detail: r.reasoning || 'no reasoning provided' })
        items.push({ source: 'discovered_at', detail: r.discovered_at })
        items.push({ source: 'last_seen_at', detail: r.last_seen_at })
    } else {
        const n = proposal.node
        if (n.first_seen_at) {
            items.push({ source: 'first_seen_at', detail: n.first_seen_at })
        }
        if (n.last_seen_at) {
            items.push({ source: 'last_seen_at', detail: n.last_seen_at })
        }
        if (n.last_traversed_at) {
            items.push({ source: 'last_traversed_at', detail: n.last_traversed_at })
        }
        if (n.reviewed_at) {
            items.push({ source: 'reviewed_at', detail: n.reviewed_at })
        }
    }
    if (items.length === 0) {
        return <></>
    }
    return (
        <section>
            <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Why</h4>
            <ul className="flex flex-col gap-1.5 text-sm">
                {items.map((p, i) => (
                    <li key={i} className="flex gap-2">
                        <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-fill-highlight-50 shrink-0 self-start">
                            {p.source}
                        </span>
                        {p.detail ? <span className="text-muted-alt">{p.detail}</span> : null}
                    </li>
                ))}
            </ul>
        </section>
    )
}

function ActionBar({
    proposal,
    onApprove,
    onMarkOfficial,
    onMarkStale,
    onOpenReject,
}: {
    proposal: Proposal
    onApprove: () => void
    onMarkOfficial: () => void
    onMarkStale: () => void
    onOpenReject: () => void
}): JSX.Element {
    const isRelationship = proposal.kind === 'relationship_proposed'

    return (
        <div className="flex items-center gap-2 flex-wrap">
            <LemonButton type="primary" icon={<IconCheckCircle />} onClick={onApprove}>
                {isRelationship ? 'Accept' : proposal.kind === 'node_drift' ? 'Acknowledge' : 'Approve'}
            </LemonButton>
            {!isRelationship ? (
                <LemonButton icon={<IconStar />} onClick={onMarkOfficial}>
                    Mark official
                </LemonButton>
            ) : null}
            {isRelationship ? (
                <>
                    <LemonButton icon={<IconArchive />} onClick={onMarkStale}>
                        Mark stale
                    </LemonButton>
                    <LemonButton status="danger" icon={<IconX />} onClick={onOpenReject}>
                        Reject
                    </LemonButton>
                </>
            ) : null}
            <div className="ml-auto text-xs text-muted-alt">
                <kbd className="px-1 py-0.5 border rounded text-[10px]">A</kbd> approve ·{' '}
                <kbd className="px-1 py-0.5 border rounded text-[10px]">J</kbd>/
                <kbd className="px-1 py-0.5 border rounded text-[10px]">K</kbd> navigate
            </div>
        </div>
    )
}

function CodeView({ proposal }: { proposal: Proposal }): JSX.Element {
    const payload = proposal.kind === 'relationship_proposed' ? proposal.relationship : proposal.node
    return (
        <section className="flex flex-col gap-2">
            <div className="text-xs text-muted-alt">
                This is the DTO the catalog API returns for this proposal — the same shape MCP and CLI tooling reads.
            </div>
            <pre className="text-xs bg-bg-3000 border rounded p-3 overflow-x-auto whitespace-pre">
                {JSON.stringify(payload, null, 2)}
            </pre>
        </section>
    )
}
