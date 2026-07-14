import { useValues } from 'kea'

import { proposalListLogic } from '../logics/proposalListLogic'
import { CardSkeleton } from './cards/CardSkeleton'
import { ProposalCard } from './cards/ProposalCard'

/**
 * Cold-start body for the Reports tab: when the regular list is empty, surface the setup-audit
 * proposals (PRs we'd like to open to improve the team's PostHog setup) instead of a dead end.
 * Falls back to the tab's default empty state when there are no proposals either.
 */
export function ProposalsColdStart({ fallback }: { fallback: JSX.Element }): JSX.Element {
    const { proposals, isLoaded, proposalsResponseLoading } = useValues(proposalListLogic)

    if (!isLoaded) {
        return proposalsResponseLoading ? <CardSkeleton count={2} variant="cards" dashed /> : fallback
    }
    if (proposals.length === 0) {
        return fallback
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="mx-auto max-w-md flex flex-col items-center text-center pt-8 gap-1">
                <h3 className="text-base font-semibold m-0">No reports yet — but we have some ideas</h3>
                <p className="text-sm text-tertiary m-0">
                    We looked at your PostHog setup and drafted a few improvements. Approve one and an agent will
                    implement it in your repo and open a draft PR.
                </p>
            </div>
            <div className="flex flex-col gap-1.5">
                {proposals.map((report) => (
                    <ProposalCard key={report.id} report={report} />
                ))}
            </div>
        </div>
    )
}
