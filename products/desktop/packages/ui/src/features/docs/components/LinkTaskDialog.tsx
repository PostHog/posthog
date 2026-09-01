import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Spinner,
  Text,
} from "@posthog/quill";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useMemo, useState } from "react";

export interface PickedTask {
  taskId: string;
  label: string;
}

const MAX_TASK_RESULTS = 20;

/** Links a task that already exists into a doc. */
export function LinkTaskDialog({
  open,
  onOpenChange,
  channelId,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  channelId: string;
  onConfirm: (task: PickedTask) => void;
}) {
  const [search, setSearch] = useState("");
  const { data: tasks, isLoading } = useTasks(
    { showAllUsers: true },
    { enabled: open },
  );

  const results = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (tasks ?? [])
      .filter((task) => task.channel === channelId)
      .filter((task) => !needle || task.title.toLowerCase().includes(needle))
      .slice(0, MAX_TASK_RESULTS);
  }, [tasks, channelId, search]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Link a task</DialogTitle>
          <DialogDescription>
            The chip shows the task's status and opens it when you click it.
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-3">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search tasks in this space"
            autoFocus
          />
          {isLoading ? (
            <div className="flex justify-center py-6">
              <Spinner />
            </div>
          ) : results.length === 0 ? (
            <Text size="sm" className="py-6 text-center text-(--gray-11)">
              No tasks in this space match that. Start one from a line instead.
            </Text>
          ) : (
            <ul className="flex flex-col gap-1">
              {results.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    className="w-full truncate rounded-(--radius-2) px-2 py-1.5 text-left hover:bg-(--gray-3)"
                    onClick={() => {
                      onConfirm({ taskId: task.id, label: task.title });
                      onOpenChange(false);
                    }}
                  >
                    {task.title}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
