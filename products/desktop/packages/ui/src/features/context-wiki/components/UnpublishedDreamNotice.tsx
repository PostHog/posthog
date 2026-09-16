import { WarningCircleIcon } from "@phosphor-icons/react";
import type { ContextWikiUnpublishedDreamRun } from "@posthog/api-client/posthog-client";
import { Button, Text } from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import type { ReactElement } from "react";

export function UnpublishedDreamNotice({
  run,
}: {
  run: ContextWikiUnpublishedDreamRun;
}): ReactElement {
  return (
    <div className="flex flex-col gap-2 border-(--gray-5) border-b bg-(--gray-2) px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <WarningCircleIcon className="shrink-0" size={16} />
          <Text size="sm" weight="medium">
            {run.run_status === "failed"
              ? "Dream failed"
              : run.run_status === "cancelled"
                ? "Dream canceled"
                : "No update published"}
          </Text>
        </div>
        <RelativeTimestamp timestamp={run.started_at} />
      </div>
      <Text size="xs" variant="muted">
        This dream ended without a published update. Open the task to see
        whether it found no changes or could not publish.
      </Text>
      <Button
        variant="outline"
        size="sm"
        nativeButton={false}
        role="link"
        render={
          <a href={run.task_url} target="_blank" rel="noopener noreferrer">
            View task
          </a>
        }
      />
    </div>
  );
}
