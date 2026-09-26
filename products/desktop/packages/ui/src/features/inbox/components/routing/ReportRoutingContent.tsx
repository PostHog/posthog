import { UsersThreeIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import {
  useReportRouting,
  useRoutingAction,
  useRoutingCatalogue,
} from "@posthog/ui/features/inbox/hooks/useInboxRouting";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { useState } from "react";
import { OwnershipPicker } from "./OwnershipPicker";
import { RoutingBatchDialog } from "./RoutingBatchDialog";

export function ReportRoutingContent({ reportId }: { reportId: string }) {
  const query = useReportRouting(reportId);
  const catalogue = useRoutingCatalogue();
  const action = useRoutingAction();
  const [batchId, setBatchId] = useState<string | null>(null);
  const state = query.data;
  const domain = state?.routing?.domain;
  const excludedDomain =
    state?.routing?.accepted &&
    catalogue.data?.preferences.some(
      (item) => item.domain.id === domain?.id && item.excluded,
    );
  return (
    <DetailSection Icon={UsersThreeIcon} title="Routing">
      <div className="flex flex-col gap-3 text-xs">
        {query.isPending ? (
          <LoadingState label="Loading routing" />
        ) : query.isError ? (
          <div role="alert">
            <p>Could not load routing.</p>
            <Button onClick={() => query.refetch()}>Try again</Button>
          </div>
        ) : (
          state && (
            <>
              <p>
                {state.routing?.explanation ||
                  "Suggested owners can take on this work. Correct the domain or team if it reached the wrong person."}
              </p>
              {state.routing && !state.routing.accepted && (
                <p>
                  The domain is uncertain. This report remains available for
                  shared triage.
                </p>
              )}
              {catalogue.isError ? (
                <div role="alert">
                  <p>Could not load domain and team choices.</p>
                  <Button onClick={() => catalogue.refetch()}>Try again</Button>
                </div>
              ) : catalogue.isPending ? (
                <LoadingState label="Loading domains" />
              ) : (
                <div className="flex flex-wrap gap-2">
                  <OwnershipPicker
                    label="Product domain"
                    value={domain?.id ?? "none"}
                    disabled={action.isPending}
                    options={[
                      { value: "none", label: "Unclassified" },
                      ...catalogue.data.domains
                        .filter((item) => !item.archived)
                        .map((item) => ({ value: item.id, label: item.name })),
                    ]}
                    onChange={(id) =>
                      action.mutate({
                        type: "correct",
                        reportId,
                        correction: { domain_id: id === "none" ? null : id },
                      })
                    }
                  />
                  <OwnershipPicker
                    label="Responsible team"
                    value={state.routing?.owning_role_id ?? "none"}
                    disabled={action.isPending}
                    options={[
                      { value: "none", label: "No team" },
                      ...catalogue.data.teams.map((item) => ({
                        value: item.id,
                        label: item.name,
                      })),
                    ]}
                    onChange={(id) =>
                      action.mutate({
                        type: "correct",
                        reportId,
                        correction: {
                          domain_id: state.routing?.accepted
                            ? (domain?.id ?? null)
                            : null,
                          owning_role_id: id === "none" ? null : id,
                        },
                      })
                    }
                  />
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={
                    action.isPending ||
                    !!(state.personal.excluded && excludedDomain)
                  }
                  onClick={() =>
                    action.mutate({
                      type: state.personal.excluded ? "restore" : "not-me",
                      reportId,
                    })
                  }
                >
                  {state.personal.excluded
                    ? "Undo Not me"
                    : state.personal.has_active_claim
                      ? "Remove my suggestion"
                      : "Not me"}
                </Button>
                {domain && state.routing?.accepted && (
                  <Button
                    variant="outline"
                    disabled={action.isPending}
                    onClick={() =>
                      action.mutate(
                        { type: "preview", domainId: domain.id },
                        {
                          onSuccess: (result) => {
                            if ("status" in result) setBatchId(result.id);
                          },
                        },
                      )
                    }
                  >{`Stop suggesting ${domain.name} to me`}</Button>
                )}
              </div>
              {state.personal.excluded && (
                <p>
                  You will not be automatically suggested again for this report.
                </p>
              )}
              {state.personal.excluded && excludedDomain && (
                <p>
                  A domain rule still applies. Manage your rules in Settings →
                  Agents → Connections.
                </p>
              )}
              {state.personal.has_active_claim && (
                <p>
                  You still own work on this report. Release or hand off that
                  work separately.
                </p>
              )}
            </>
          )
        )}
        {action.isError && (
          <p role="alert">
            Could not save routing. Check your domain rules and try again.
          </p>
        )}
        {batchId && (
          <RoutingBatchDialog
            key={batchId}
            batchId={batchId}
            onClose={() => setBatchId(null)}
          />
        )}
      </div>
    </DetailSection>
  );
}
