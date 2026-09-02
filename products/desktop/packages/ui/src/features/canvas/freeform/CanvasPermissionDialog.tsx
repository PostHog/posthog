import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { PermissionSelector } from "@posthog/ui/features/permissions/PermissionSelector";
import {
  useModeConfigOptionForTask,
  usePendingPermissionsForTask,
} from "@posthog/ui/features/sessions/useSession";
import { toast } from "@posthog/ui/primitives/toast";
import { Dialog, VisuallyHidden } from "@radix-ui/themes";
import { useCallback, useMemo } from "react";

// Surfaces a generating canvas's pending permission request (e.g. an MCP tool
// approval) right on the canvas screen, so the user never has to open the task
// to unblock it. Reuses the task view's PermissionSelector + the same
// SessionService response path; the request itself lives in the global session
// store, populated by the gen task's live session — which is exactly the
// session that keeps the canvas in its "generating" state. When no request is
// pending the dialog stays closed.
export function CanvasPermissionDialog({ taskId }: { taskId: string }) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const pendingPermissions = usePendingPermissionsForTask(taskId);
  const modeOption = useModeConfigOptionForTask(taskId);

  // The session log resolves one request at a time (oldest first); mirror that.
  const firstPendingPermission = useMemo(() => {
    const entries = Array.from(pendingPermissions.entries());
    if (entries.length === 0) return null;
    const [toolCallId, permission] = entries[0];
    return { ...permission, toolCallId };
  }, [pendingPermissions]);

  const handleSelect = useCallback(
    async (
      optionId: string,
      customInput?: string,
      answers?: Record<string, string>,
    ) => {
      if (!firstPendingPermission) return;
      try {
        const plan = await sessionService.resolvePermissionSelection(
          taskId,
          firstPendingPermission,
          optionId,
          modeOption,
          customInput,
          answers,
        );
        // "Type here to tell the agent…" with no custom-input option attached
        // is re-sent as a steering prompt, same as the task view. The response
        // is already resolved by here, so a send failure must be surfaced —
        // otherwise the user's text is silently dropped.
        if (plan.resendPromptText) {
          await sessionService.sendPrompt(taskId, plan.resendPromptText);
        }
      } catch (error) {
        toast.error("Couldn't send your response to the agent", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [firstPendingPermission, taskId, modeOption, sessionService],
  );

  const handleCancel = useCallback(async () => {
    if (!firstPendingPermission) return;
    try {
      await sessionService.cancelPermissionAndPrompt(
        taskId,
        firstPendingPermission.toolCallId,
      );
    } catch (error) {
      toast.error("Couldn't cancel the request", {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  }, [firstPendingPermission, taskId, sessionService]);

  const open = !!firstPendingPermission;

  return (
    <Dialog.Root open={open}>
      <Dialog.Content
        maxWidth="560px"
        // Require an explicit choice: outside clicks don't dismiss; Esc rejects
        // the request (PermissionSelector's own Esc also routes to onCancel).
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => {
          e.preventDefault();
          void handleCancel();
        }}
      >
        <VisuallyHidden>
          <Dialog.Title>Canvas needs your approval</Dialog.Title>
        </VisuallyHidden>
        {firstPendingPermission && (
          <PermissionSelector
            toolCall={firstPendingPermission.toolCall}
            options={firstPendingPermission.options}
            onSelect={handleSelect}
            onCancel={handleCancel}
          />
        )}
      </Dialog.Content>
    </Dialog.Root>
  );
}
