import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { TaskFeedModal } from "@posthog/ui/features/canvas/components/TaskFeedModal";
import { useTaskFeedSelectionStore } from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { type ReactNode, useState } from "react";

export function useSavedSearchActions(feed: TaskFeed | undefined): {
  openEdit: () => void;
  requestDelete: () => void;
  dialogs: ReactNode;
} {
  const navigate = useNavigate();
  const removeFeed = useTaskFeedsStore((state) => state.removeFeed);
  const select = useTaskFeedSelectionStore((state) => state.select);
  const [editOpen, setEditOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const remove = () => {
    if (!feed) return;
    removeFeed(feed.id);
    select(null);
    track(ANALYTICS_EVENTS.TASK_FEED_ACTION, {
      action_type: "delete",
      surface: "feed_home",
      feed_id: feed.id,
    });
    toast.success("Saved search deleted");
    void navigate({ to: "/spaces" });
  };

  const dialogs = !feed ? null : (
    <>
      <TaskFeedModal open={editOpen} onOpenChange={setEditOpen} feed={feed} />
      <AlertDialog open={confirmDeleteOpen} onOpenChange={setConfirmDeleteOpen}>
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete saved search?</AlertDialogTitle>
            <AlertDialogDescription>
              Delete <span className="font-medium">{feed.name}</span>? You
              cannot undo this action.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button variant="outline" size="sm">
                  Cancel
                </Button>
              }
            />
            <Button variant="destructive" size="sm" onClick={remove}>
              Delete
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );

  return {
    openEdit: () => setEditOpen(true),
    requestDelete: () => setConfirmDeleteOpen(true),
    dialogs,
  };
}
