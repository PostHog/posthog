import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import { useGenerateFreeformCanvas } from "@posthog/ui/features/canvas/hooks/useGenerateFreeformCanvas";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import {
  type WorkspaceMode,
  WorkspaceModeSelect,
} from "@posthog/ui/features/task-detail/components/WorkspaceModeSelect";
import { forwardRef, useState } from "react";

// Composer that kicks off freeform canvas generation as a dedicated task: the
// user describes what they want and the agent builds + publishes the canvas. No
// repo is picked up front — the agent attaches one lazily only if it needs it.
// Used both for the first build (empty canvas) and for follow-up edits
// (currentCode passed in).
//
// Shares the task composer's editor (PromptInput) so it matches it exactly — @
// for files, / for skills, ↑↓ for history — but renders a blank toolbar for now:
// just the send button, none of the attach/mode/model/history addons. The
// forwarded ref exposes the editor handle so callers can prefill it (suggestion
// cards, self-repair).
export const FreeformGenerateBar = forwardRef<
  EditorHandle,
  {
    dashboardId: string;
    channelId: string;
    channelName: string;
    name: string;
    templateId?: string;
    currentCode?: string;
    // Keys the editor's draft/command state; distinct per canvas.
    sessionId: string;
    onStarted?: (taskId: string) => void;
  }
>(function FreeformGenerateBar(
  {
    dashboardId,
    channelId,
    channelName,
    name,
    templateId,
    currentCode,
    sessionId,
    onStarted,
  },
  ref,
) {
  const { generate, isStarting } = useGenerateFreeformCanvas({
    channelId,
    channelName,
  });

  // On a FIRST build we seed the agent with a known-good starter scaffold by
  // default (faster, more consistent than authoring from scratch). Uncheck to
  // opt out and have the agent build from a blank canvas. Only meaningful on an
  // empty canvas, so the toggle is hidden in edit mode.
  const isEdit = !!currentCode?.trim();
  const [useStarter, setUseStarter] = useState(true);

  // Generation always runs in the cloud, except the dev-only picker below lets a
  // local build of these features be tested before it's merged to the cloud env.
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("cloud");

  const run = async (text: string) => {
    const instruction = text.trim();
    if (!instruction) return;
    const taskId = await generate({
      dashboardId,
      name,
      templateId,
      instruction,
      currentCode,
      useStarter: !isEdit && useStarter,
      workspaceMode,
    });
    if (taskId) onStarted?.(taskId);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <PromptInput
        ref={ref}
        sessionId={sessionId}
        editorHeight="large"
        disabled={isStarting}
        isLoading={isStarting}
        enableCommands
        enableBashMode={false}
        hideDefaultToolbar
        onSubmit={(text) => void run(text)}
      />
      {!isEdit && (
        <label className="flex cursor-pointer select-none items-center gap-1.5 self-start px-1 text-muted-foreground text-xs">
          <input
            type="checkbox"
            className="cursor-pointer"
            checked={useStarter}
            disabled={isStarting}
            onChange={(e) => setUseStarter(e.target.checked)}
          />
          Start from scaffold (faster, more consistent — uncheck to build from
          scratch)
        </label>
      )}
      {/* Dev-only: pick local vs cloud so a local build can be tested pre-merge. */}
      {import.meta.env.DEV && (
        <Tooltip>
          <TooltipTrigger render={<div className="self-start px-1" />}>
            <WorkspaceModeSelect
              value={workspaceMode}
              onChange={setWorkspaceMode}
              overrideModes={["local", "cloud"]}
              disabled={isStarting}
              size="1"
            />
          </TooltipTrigger>
          <TooltipContent>
            Dev mode only — generation always runs in the cloud in production.
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
});
