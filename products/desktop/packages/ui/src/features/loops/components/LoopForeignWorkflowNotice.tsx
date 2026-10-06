import { ArrowSquareOut } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

/**
 * Shown in place of the configuration summary when the workflow behind a loop
 * no longer has the shape the loop editor writes. Saving from here would
 * replace the whole graph, so editing moves to the workflow editor.
 */
export function LoopForeignWorkflowNotice({
  workflowUrl,
}: {
  workflowUrl: string | null;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-3 py-3">
      <span className="font-medium text-(--amber-12) text-[12.5px]">
        This loop was changed in the workflow editor
      </span>
      <span className="text-(--amber-11) text-[12px] leading-snug">
        It now has steps or triggers the loop editor can't show. Open it in
        PostHog to change it, or delete it here. Run history and the pause
        toggle still work.
      </span>
      {workflowUrl ? (
        <Button
          variant="outline"
          size="sm"
          className="w-fit"
          onClick={() => openExternalUrl(workflowUrl)}
        >
          <ArrowSquareOut size={14} />
          Open in PostHog
        </Button>
      ) : null}
    </div>
  );
}
