import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { CodeBlock } from "@posthog/ui/primitives/CodeBlock";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { formatCapturedLogs } from "@posthog/ui/shell/logCapture";
import { serializeError, useErrorDetailsStore } from "./errorDetails";

// Keep the create-task prompt readable: the full 500-entry buffer belongs in
// the downloaded bundle, not in a composer draft.
const TASK_PROMPT_LOG_ENTRIES = 100;

function buildBundle(
  title: string,
  occurredAt: number,
  prettyError: string,
): string {
  return [
    `# ${title}`,
    `Occurred at: ${new Date(occurredAt).toISOString()}`,
    "",
    "## Error",
    prettyError,
    "",
    "## Recent logs",
    formatCapturedLogs(),
    "",
  ].join("\n");
}

// Global inspector behind every error toast's "Details" action: the full
// pretty-printed payload the toast had no room for, a downloadable
// error-plus-logs bundle, and (dev builds only) a one-click task prefilled
// with the same context.
export function ErrorDetailsDialog() {
  const detail = useErrorDetailsStore((s) => s.detail);
  const close = useErrorDetailsStore((s) => s.close);
  if (!detail) return null;

  const prettyError = serializeError(detail.error);

  const handleDownload = () => {
    const bundle = buildBundle(detail.title, detail.occurredAt, prettyError);
    const blob = new Blob([bundle], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `posthog-code-error-${detail.occurredAt}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const handleCreateTask = () => {
    close();
    openTaskInput({
      initialPrompt: [
        `Investigate this error from the PostHog app: ${detail.title}`,
        "",
        "## Error",
        "```",
        prettyError,
        "```",
        "",
        "## Recent logs",
        "```",
        formatCapturedLogs({ maxEntries: TASK_PROMPT_LOG_ENTRIES }),
        "```",
      ].join("\n"),
    });
  };

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="w-[min(720px,calc(100vw-32px))] max-w-[720px] sm:max-w-[720px]">
        <DialogHeader>
          <DialogTitle>{detail.title}</DialogTitle>
        </DialogHeader>
        <div className="max-h-[55vh] overflow-y-auto px-1">
          <CodeBlock size="1">{prettyError}</CodeBlock>
        </div>
        <DialogFooter>
          {import.meta.env.DEV && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleCreateTask}
              className="gap-2 sm:mr-auto"
            >
              Create task from error
              <Badge variant="warning">Dev</Badge>
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleDownload}>
            Download error + logs
          </Button>
          <Button variant="primary" size="sm" onClick={close}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
