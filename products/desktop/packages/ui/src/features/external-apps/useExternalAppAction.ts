import type { ExternalAppAction } from "@posthog/core/context-menu/schemas";
import type {
  ExternalAppService,
  ExternalAppWorkspaceContext,
} from "@posthog/core/external-apps/externalAppService";
import { EXTERNAL_APPS_SERVICE } from "@posthog/core/external-apps/identifiers";
import { useService } from "@posthog/di/react";
import { useCallback } from "react";
import { toast } from "../../primitives/toast";
import { showFocusSuccessToast } from "../focus/focusToast";
import { toastError } from "../notifications/errorDetails";

export function useExternalAppAction() {
  const service = useService<ExternalAppService>(EXTERNAL_APPS_SERVICE);

  return useCallback(
    async (
      action: ExternalAppAction,
      filePath: string,
      displayName: string,
      workspaceContext?: ExternalAppWorkspaceContext,
    ): Promise<void> => {
      const outcome = await service.openExternalApp(
        action,
        filePath,
        displayName,
        workspaceContext,
      );

      switch (outcome.kind) {
        case "opened":
          if (outcome.focus) {
            showFocusSuccessToast(
              outcome.focus.branchName,
              outcome.focus.result,
            );
          }
          toast.success(`Opening in ${outcome.appName}`, {
            description: outcome.displayName,
          });
          return;
        case "open-failed":
          toastError("Failed to open in external app", outcome.error);
          return;
        case "focus-failed":
          toastError("Could not edit workspace", outcome.error);
          return;
        case "copied":
          toast.success("Path copied to clipboard", {
            description: outcome.filePath,
          });
          return;
      }
    },
    [service],
  );
}
