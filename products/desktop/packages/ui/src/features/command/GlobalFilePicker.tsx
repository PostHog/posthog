import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { FilePicker } from "@posthog/ui/features/command/FilePicker";
import { useFileSearchStore } from "@posthog/ui/features/command/fileSearchStore";
import { useFileSearchContext } from "@posthog/ui/features/command/useFileSearchContext";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useEffect } from "react";

export function GlobalFilePicker() {
  const open = useFileSearchStore((s) => s.pickerOpen);
  const close = useFileSearchStore((s) => s.closePicker);
  const { repoPath, recentFiles, selectFile } = useFileSearchContext();

  const handleSelectFile = useCallback(
    (path: string) => {
      track(ANALYTICS_EVENTS.COMMAND_MENU_ACTION, { action_type: "open-file" });
      selectFile(path);
    },
    [selectFile],
  );

  // Reset the flag so the picker doesn't re-open itself when a repo returns.
  useEffect(() => {
    if (open && !repoPath) close();
  }, [open, repoPath, close]);

  if (!repoPath) return null;

  return (
    <FilePicker
      open={open}
      onOpenChange={(isOpen) => !isOpen && close()}
      repoPath={repoPath}
      recentFiles={recentFiles}
      onSelectFile={handleSelectFile}
    />
  );
}
