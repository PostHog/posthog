import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import type { UseUnarchiveTask } from "./useUnarchiveTask";

const log = logger.scope("undo-archive");

const inFlight = new Set<string>();

export async function undoArchive(
  taskId: string,
  restore: UseUnarchiveTask["restore"],
): Promise<void> {
  if (inFlight.has(taskId)) return;
  inFlight.add(taskId);
  try {
    let outcome = await restore(taskId, true);
    // Undo is a transient toast action: silently recreate a missing branch
    // rather than interrupting with the Archived tasks page's confirm dialog.
    if (outcome.kind === "branch-not-found") {
      outcome = await restore(taskId, true, { recreateBranch: true });
    }
    if (outcome.kind === "restored") {
      toast.success("Task archive undone");
      return;
    }
    const reason =
      outcome.kind === "branch-not-found"
        ? `branch '${outcome.branchName}' not found`
        : outcome.message;
    log.error("Failed to restore archived task", { taskId, reason });
    toast.error(`Failed to restore task: ${reason}`);
  } catch (error) {
    log.error("Failed to restore archived task", error);
    toast.error("Failed to restore task");
  } finally {
    inFlight.delete(taskId);
  }
}
