import { Plus } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { NewCanvasDialog } from "@posthog/ui/features/canvas/components/NewCanvasMenu";
import { trackAndCreateCanvas } from "@posthog/ui/features/canvas/createCanvasAnalytics";
import { useCanvasTemplates } from "@posthog/ui/features/canvas/hooks/useCanvasTemplates";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { isContentEmpty } from "@posthog/ui/features/message-editor/content";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { SidebarKbdHint } from "@posthog/ui/features/sidebar/components/items/SidebarKbdHint";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

/**
 * The create rows that lead a space's list, one per tab: making a thing sits
 * with the list of those things, so the action follows the tab you're on
 * instead of floating in a corner over the rows.
 */
export function NewSessionRow({
  channelId,
  isActive,
}: {
  channelId: string;
  isActive: boolean;
}) {
  const navigate = useNavigate();
  const hasDraft = useDraftStore(
    (s) => !isContentEmpty(s.drafts["task-input"]),
  );

  return (
    <SidebarItem
      depth={0}
      icon={<Plus size={16} weight={isActive ? "bold" : "regular"} />}
      label="New session"
      isActive={isActive}
      onClick={() => {
        track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
          action_type: "new_task_open",
          surface: "sidebar",
          channel_id: channelId,
        });
        void navigate({
          to: "/website/$channelId/new",
          params: { channelId },
        });
      }}
      // An unsent draft is the reason to come back to this row, and this row is
      // the only place a space says you have one.
      endContent={
        hasDraft ? (
          <Badge variant="default" title="You have unsubmitted changes">
            Draft
          </Badge>
        ) : null
      }
      // ⌘N inside a space lands on this same route (openTaskInput scopes to
      // the channel you're in), so the row can claim the key.
      endHint={<SidebarKbdHint keys={SHORTCUTS.NEW_TASK} />}
    />
  );
}

export function NewCanvasRow({ channelId }: { channelId: string }) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const templates = useCanvasTemplates();
  const createAndOpen = useCreateAndOpenDashboard(channelId);
  const hasTemplates = templates.length > 0;

  return (
    <>
      <SidebarItem
        depth={0}
        icon={<Plus size={16} />}
        // Until templates load there is nothing to pick, so the click creates
        // the canvas outright — and the label drops the ellipsis with it.
        label={hasTemplates ? "New canvas…" : "New canvas"}
        onClick={() => {
          if (hasTemplates) {
            setPickerOpen(true);
            return;
          }
          trackAndCreateCanvas(
            channelId,
            undefined,
            "sidebar",
            () => void createAndOpen(),
          );
        }}
      />
      <NewCanvasDialog
        channelId={channelId}
        surface="sidebar"
        open={pickerOpen}
        onOpenChange={setPickerOpen}
      />
    </>
  );
}
