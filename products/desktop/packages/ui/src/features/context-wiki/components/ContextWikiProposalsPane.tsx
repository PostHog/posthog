import type { ContextWikiPageProposal } from "@posthog/api-client/posthog-client";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { type ReactElement, useState } from "react";
import {
  useApplyContextWikiProposal,
  useContextWikiProposals,
} from "../hooks/useContextWiki";
import { ContextWikiProposalReview } from "./ContextWikiProposalReview";
import { ContextWikiProposalsPlaceholder } from "./ContextWikiProposalsPlaceholder";

function ProposalReview({
  proposal,
}: {
  proposal: ContextWikiPageProposal;
}): ReactElement {
  const apply = useApplyContextWikiProposal();
  return (
    <ContextWikiProposalReview
      proposal={proposal}
      applying={apply.isPending}
      applied={apply.isSuccess}
      error={apply.error}
      onApply={() => apply.mutate(proposal.id)}
    />
  );
}

export function ContextWikiProposalsPane(): ReactElement {
  const proposals = useContextWikiProposals();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = proposals.data?.find(
    (proposal) => proposal.id === selectedId,
  );

  if (proposals.isLoading) return <LoadingState />;
  if (proposals.error) {
    return (
      <ContextWikiProposalsPlaceholder
        state="error"
        onRetry={() => void proposals.refetch()}
        retrying={proposals.isFetching}
      />
    );
  }
  if (!proposals.data?.length) {
    return <ContextWikiProposalsPlaceholder state="empty" />;
  }

  return (
    <div className="@container flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1 @3xl:flex-row flex-col">
        <nav
          aria-label="Suggested edits"
          className="@3xl:max-h-none max-h-48 @3xl:w-64 shrink-0 overflow-auto border-(--gray-5) @3xl:border-r border-b @3xl:border-b-0 p-3"
        >
          {proposals.data.map((proposal) => (
            <button
              key={proposal.id}
              type="button"
              aria-pressed={selectedId === proposal.id}
              className="block w-full break-all rounded p-2 text-left text-sm hover:bg-(--gray-3) aria-pressed:bg-(--gray-4)"
              onClick={() => setSelectedId(proposal.id)}
            >
              {proposal.path}
            </button>
          ))}
        </nav>
        {selected ? (
          <ProposalReview key={selected.id} proposal={selected} />
        ) : (
          <ContextWikiProposalsPlaceholder state="unselected" />
        )}
      </div>
    </div>
  );
}
