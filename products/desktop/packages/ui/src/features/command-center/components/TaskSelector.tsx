import {
  ArrowLeft,
  Folder,
  Lightning,
  Plus,
  Terminal,
} from "@phosphor-icons/react";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { Popover } from "@radix-ui/themes";
import { type ReactNode, useCallback, useState } from "react";
import { Combobox } from "../../../primitives/combobox/Combobox";
import { useFolders } from "../../folders/useFolders";
import { useCommandCenterStore } from "../commandCenterStore";
import { useAvailableTasks } from "../hooks/useAvailableTasks";

interface TaskSelectorProps {
  cellIndex: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNewTask?: () => void;
  onNewTerminal?: (cwd?: string) => void;
  onBrainrot?: () => void;
  children: ReactNode;
}

export function TaskSelector({
  cellIndex,
  open,
  onOpenChange,
  onNewTask,
  onNewTerminal,
  onBrainrot,
  children,
}: TaskSelectorProps) {
  const availableTasks = useAvailableTasks();
  const assignTask = useCommandCenterStore((s) => s.assignTask);
  const { getRecentFolders } = useFolders();
  const folders = getRecentFolders();
  const [step, setStep] = useState<"tasks" | "folder">("tasks");

  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) setStep("tasks");
      onOpenChange(next);
    },
    [onOpenChange],
  );

  const handleSelect = useCallback(
    (value: string) => {
      if (step === "folder") {
        onNewTerminal?.(value);
      } else {
        assignTask(cellIndex, value);
      }
      handleOpenChange(false);
    },
    [step, onNewTerminal, assignTask, cellIndex, handleOpenChange],
  );

  const handleNewTask = useCallback(() => {
    handleOpenChange(false);
    if (onNewTask) {
      onNewTask();
    } else {
      openTaskInput();
    }
  }, [handleOpenChange, onNewTask]);

  const handleNewTerminal = useCallback(() => {
    if (folders.length > 1) {
      setStep("folder");
      return;
    }
    handleOpenChange(false);
    onNewTerminal?.(folders[0]?.path);
  }, [folders, handleOpenChange, onNewTerminal]);

  const handleBrainrot = useCallback(() => {
    handleOpenChange(false);
    onBrainrot?.();
  }, [handleOpenChange, onBrainrot]);

  return (
    <Combobox.Root
      open={open}
      onOpenChange={handleOpenChange}
      value=""
      onValueChange={handleSelect}
      size="1"
    >
      <Popover.Trigger>{children}</Popover.Trigger>
      {step === "folder" ? (
        <Combobox.Content
          items={folders}
          getValue={(folder) => folder.name}
          side="bottom"
          align="center"
          sideOffset={4}
          className="min-w-[240px]"
        >
          {({ filtered }) => (
            <>
              <Combobox.Input placeholder="Search folders..." />
              <Combobox.Empty>No matching folders</Combobox.Empty>
              {filtered.map((folder) => (
                <Combobox.Item
                  key={folder.id}
                  value={folder.path}
                  textValue={folder.name}
                  icon={<Folder size={12} />}
                  description={folder.path}
                >
                  {folder.name}
                </Combobox.Item>
              ))}
              <Combobox.Footer>
                <button
                  type="button"
                  className="combobox-footer-button"
                  onClick={() => setStep("tasks")}
                >
                  <ArrowLeft size={11} weight="bold" />
                  Back
                </button>
              </Combobox.Footer>
            </>
          )}
        </Combobox.Content>
      ) : (
        <Combobox.Content
          items={availableTasks}
          getValue={(task) => task.title}
          side="bottom"
          align="center"
          sideOffset={4}
          className="min-w-[240px]"
        >
          {({ filtered, hasMore, moreCount }) => (
            <>
              <Combobox.Input placeholder="Search tasks..." />
              <Combobox.Empty>No matching tasks</Combobox.Empty>
              {filtered.map((task) => (
                <Combobox.Item
                  key={task.id}
                  value={task.id}
                  textValue={task.title}
                >
                  {task.title}
                </Combobox.Item>
              ))}
              {hasMore && (
                <div className="combobox-label">
                  {moreCount} more {moreCount === 1 ? "task" : "tasks"}; type to
                  filter
                </div>
              )}
              <Combobox.Footer>
                <button
                  type="button"
                  className="combobox-footer-button"
                  onClick={handleNewTask}
                >
                  <Plus size={11} weight="bold" />
                  New task
                </button>
                {onNewTerminal && (
                  <button
                    type="button"
                    className="combobox-footer-button"
                    onClick={handleNewTerminal}
                  >
                    <Terminal size={11} weight="bold" />
                    Terminal
                  </button>
                )}
                {onBrainrot && (
                  <button
                    type="button"
                    className="combobox-footer-button"
                    onClick={handleBrainrot}
                  >
                    <Lightning size={11} weight="bold" />
                    Brainrot
                  </button>
                )}
              </Combobox.Footer>
            </>
          )}
        </Combobox.Content>
      )}
    </Combobox.Root>
  );
}
