import { Button } from "@posthog/quill";
import {
  useRoutingAction,
  useRoutingCatalogue,
} from "@posthog/ui/features/inbox/hooks/useInboxRouting";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useState } from "react";
import { RoutingBatchDialog } from "./RoutingBatchDialog";

export function InboxRoutingPreferencesContent() {
  const catalogue = useRoutingCatalogue();
  const action = useRoutingAction();
  const [batchId, setBatchId] = useState<string | null>(null);
  return (
    <section
      className="flex flex-col gap-3 py-4 text-xs"
      aria-label="Your routing"
    >
      <h3 className="font-semibold text-foreground">Your routing</h3>
      <p>
        Choose the domains you can own. Your rules affect your suggestions.
        Allowing suggestions again does not refill your backlog.
      </p>
      {catalogue.isPending ? (
        <LoadingState label="Loading routing preferences" />
      ) : catalogue.isError ? (
        <div role="alert">
          <p>Could not load your rules.</p>
          <Button onClick={() => catalogue.refetch()}>Try again</Button>
        </div>
      ) : (
        <>
          {catalogue.data.domains.length === 0 && (
            <p>
              No product domains yet. Add shared definitions in the web inbox
              settings.
            </p>
          )}
          <ul className="flex flex-col gap-3">
            {catalogue.data.domains.map((domain) => {
              const excluded = catalogue.data.preferences.some(
                (rule) => rule.domain.id === domain.id && rule.excluded,
              );
              return (
                <li
                  key={domain.id}
                  className="flex flex-wrap items-center justify-between gap-2 border-border border-b pb-3"
                >
                  <div className="min-w-0">
                    <p className="break-words font-medium">{domain.name}</p>
                    <p className="text-muted-foreground">
                      {domain.owning_role_name || "No team"}
                    </p>
                    <p>{excluded ? "Excluded" : "Eligible for suggestions"}</p>
                  </div>
                  <Button
                    variant="outline"
                    disabled={
                      action.isPending || (!excluded && domain.archived)
                    }
                    onClick={() =>
                      action.mutate(
                        {
                          type: excluded ? "allow" : "preview",
                          domainId: domain.id,
                        },
                        {
                          onSuccess: (result) => {
                            if ("status" in result) setBatchId(result.id);
                          },
                        },
                      )
                    }
                  >
                    {excluded ? "Allow suggestions" : "Exclude domain…"}
                  </Button>
                </li>
              );
            })}
          </ul>
          {catalogue.data.batches.some(
            (batch) => batch.status !== "preview",
          ) && (
            <>
              <h4 className="font-semibold">Recent changes</h4>
              <div className="flex flex-wrap gap-2">
                {catalogue.data.batches
                  .filter((batch) => batch.status !== "preview")
                  .map((batch) => (
                    <Button
                      key={batch.id}
                      variant="outline"
                      onClick={() => setBatchId(batch.id)}
                    >{`${catalogue.data.domains.find((domain) => domain.id === batch.domain_id)?.name ?? "Domain"}: ${batch.status}`}</Button>
                  ))}
              </div>
            </>
          )}
        </>
      )}
      {action.isError && (
        <p role="alert">Could not update your routing. Try again.</p>
      )}
      {batchId && (
        <RoutingBatchDialog
          key={batchId}
          batchId={batchId}
          onClose={() => setBatchId(null)}
        />
      )}
    </section>
  );
}
