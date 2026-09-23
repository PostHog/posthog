import type { InboxScope } from "@posthog/core/inbox/reportMembership";
import { getSuggestedReviewerDisplayName } from "@posthog/ui/features/inbox/filterOptions";
import { useRoutingCatalogue } from "@posthog/ui/features/inbox/hooks/useInboxRouting";
import { useInboxScopeOptions } from "@posthog/ui/features/inbox/hooks/useInboxScopeOptions";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { OwnershipPicker } from "./OwnershipPicker";

export function CurrentOwnershipScopeSelect() {
  const scope = useInboxReviewerScopeStore((state) => state.scope);
  const setScope = useInboxReviewerScopeStore((state) => state.setScope);
  const catalogue = useRoutingCatalogue();
  const { teammateOptions } = useInboxScopeOptions();
  const options = [
    { value: "for-you", label: "For you" },
    ...(catalogue.data?.teams.map((team) => ({
      value: `team:${team.id}`,
      label: `${team.name}${team.is_member ? " (your team)" : " team"}`,
    })) ?? []),
    ...(catalogue.data?.domains
      .filter((domain) => !domain.archived)
      .map((domain) => ({
        value: `domain:${domain.id}`,
        label: domain.name,
      })) ?? []),
    ...teammateOptions.map((person) => ({
      value: `teammate:${person.uuid}`,
      label: getSuggestedReviewerDisplayName(person),
    })),
    { value: "unclassified", label: "Unclassified" },
    { value: "entire-project", label: "Entire project" },
  ];
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <OwnershipPicker
        label="Inbox scope"
        value={scope}
        options={options}
        onChange={(value) => setScope(value as InboxScope)}
      />
      {catalogue.isError && (
        <button
          type="button"
          className="text-xs underline"
          onClick={() => catalogue.refetch()}
        >
          Could not load teams and domains. Try again.
        </button>
      )}
    </div>
  );
}
