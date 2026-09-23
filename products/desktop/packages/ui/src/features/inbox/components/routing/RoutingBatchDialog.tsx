import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import {
  useRoutingAction,
  useRoutingBatch,
  useRoutingBatchReports,
  useRoutingCatalogue,
} from "@posthog/ui/features/inbox/hooks/useInboxRouting";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

export function RoutingBatchDialog({
  batchId,
  onClose,
}: {
  batchId: string;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const batchQuery = useRoutingBatch(batchId);
  const catalogue = useRoutingCatalogue();
  const reports = useRoutingBatchReports(batchId, offset);
  const action = useRoutingAction();
  const batch = batchQuery.data;
  const domain = catalogue.data?.domains.find(
    (domain) => domain.id === batch?.domain_id,
  );
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {domain ? `Your routing for ${domain.name}` : "Your routing change"}
          </DialogTitle>
          <DialogDescription>
            Remove your suggestions and remember this domain rule. Reports
            remain available to your team. Work you own stays assigned.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3 text-xs">
            {batchQuery.isPending ? (
              <LoadingState label="Loading routing change" />
            ) : batchQuery.isError ? (
              <div role="alert">
                <p>Could not load this change.</p>
                <Button onClick={() => batchQuery.refetch()}>Try again</Button>
              </div>
            ) : (
              batch && (
                <>
                  {batch.status === "preview" ? (
                    <p>
                      {batch.total}{" "}
                      {batch.total === 1 ? "report matches" : "reports match"}{" "}
                      this preview. Review before saving. Reports changed after
                      this preview may be skipped.
                    </p>
                  ) : (
                    <p>
                      {`Removed from ${batch.changed} of ${batch.total} reports. Kept ${batch.skipped_claims} for active work and skipped ${batch.skipped_changes} after changes. `}
                      Your rule takes effect immediately. Cleanup continues
                      after closing this window. Undo preserves newer edits and
                      rules.
                    </p>
                  )}
                  {reports.isPending ? (
                    <LoadingState label="Loading affected reports" />
                  ) : reports.isError ? (
                    <div role="alert">
                      <p>Could not load affected reports.</p>
                      <Button onClick={() => reports.refetch()}>
                        Try again
                      </Button>
                    </div>
                  ) : (
                    <>
                      {reports.data.results.length === 0 && (
                        <p>
                          No matching suggestions. You can still remember the
                          rule for future reports.
                        </p>
                      )}
                      <ul className="flex max-h-64 flex-col gap-2 overflow-y-auto">
                        {reports.data.results.map((report) => (
                          <li
                            key={report.report_id}
                            className="flex flex-wrap justify-between gap-2"
                          >
                            <Link
                              to="/reports/$reportId"
                              params={{ reportId: report.report_id }}
                              className="min-w-0 break-words underline"
                            >
                              {report.title || "Untitled report"}
                            </Link>
                            <span className="text-muted-foreground">
                              {report.has_active_claim
                                ? "Keep active work"
                                : report.status}
                            </span>
                          </li>
                        ))}
                      </ul>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          disabled={offset === 0}
                          onClick={() => setOffset(Math.max(0, offset - 20))}
                        >
                          Previous
                        </Button>
                        <Button
                          variant="outline"
                          disabled={!reports.data.next}
                          onClick={() => setOffset(offset + 20)}
                        >
                          Next
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            void batchQuery.refetch();
                            void reports.refetch();
                          }}
                        >
                          Refresh
                        </Button>
                      </div>
                    </>
                  )}
                  {action.isError && (
                    <p role="alert">
                      Could not save this change. Refresh its status or create a
                      new preview.
                    </p>
                  )}
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button variant="outline" onClick={onClose}>
                      Close
                    </Button>
                    {batch.status === "preview" && (
                      <Button
                        variant="primary"
                        disabled={
                          action.isPending || !reports.data || reports.isError
                        }
                        onClick={() =>
                          action.mutate({ type: "apply", batchId })
                        }
                      >
                        {action.isPending
                          ? "Saving…"
                          : "Remove me and remember"}
                      </Button>
                    )}
                    {["pending", "running", "complete", "failed"].includes(
                      batch.status,
                    ) && (
                      <Button
                        variant="outline"
                        disabled={action.isPending}
                        onClick={() => action.mutate({ type: "undo", batchId })}
                      >
                        Undo this operation
                      </Button>
                    )}
                    {batch.status === "failed" &&
                      batch.error === "cleanup_failed" && (
                        <Button
                          variant="primary"
                          disabled={action.isPending}
                          onClick={() =>
                            action.mutate({ type: "retry", batchId })
                          }
                        >
                          Retry cleanup
                        </Button>
                      )}
                  </div>
                </>
              )
            )}
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
