import { HomeView } from "@posthog/ui/features/prototypes/tags/HomeView";
import {
  type PrototypeTask,
  TAGS,
  TASKS,
} from "@posthog/ui/features/prototypes/tags/mockData";
import { NewTaskDialog } from "@posthog/ui/features/prototypes/tags/NewTaskDialog";
import { PrototypeSidebar } from "@posthog/ui/features/prototypes/tags/PrototypeSidebar";
import { TagView } from "@posthog/ui/features/prototypes/tags/TagView";
import { TaskPanel } from "@posthog/ui/features/prototypes/tags/TaskPanel";
import { useState } from "react";

export type PrototypeView = { kind: "home" } | { kind: "tag"; tagId: string };

/**
 * Clickable prototype: what the app could feel like if spaces became flat,
 * many-to-many tags with startup metadata (repos + context), a single global
 * left nav, and a Linear-style Home for staying on top of many agents at once.
 *
 * Everything is local state over invented fixtures — no routing, no stores,
 * no backend. Not production code.
 */
export function TagsPrototype() {
  const [view, setView] = useState<PrototypeView>({ kind: "home" });
  const [tasks, setTasks] = useState<PrototypeTask[]>(TASKS);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [newTaskOpen, setNewTaskOpen] = useState(false);

  const selectedTask = tasks.find((t) => t.id === selectedTaskId) ?? null;

  const openTag = (tagId: string) => {
    setView({ kind: "tag", tagId });
  };

  const toggleTag = (taskId: string, tagId: string) => {
    setTasks((prev) =>
      prev.map((task) => {
        if (task.id !== taskId) return task;
        const has = task.tagIds.includes(tagId);
        if (has && task.tagIds.length === 1) return task;
        return {
          ...task,
          tagIds: has
            ? task.tagIds.filter((t) => t !== tagId)
            : [...task.tagIds, tagId],
        };
      }),
    );
  };

  const startTask = (title: string, tagIds: string[]) => {
    const task: PrototypeTask = {
      id: `new-${Date.now()}`,
      title,
      tagIds,
      status: "running",
      statusDetail: "Cloning repos and loading tag context…",
      ownerId: "you",
      participantIds: ["you"],
      repo: "acme/webapp",
      updated: "just now",
      progress: 5,
      activity: [
        { time: "now", actor: "you", text: "Started the task." },
        {
          time: "now",
          actor: "agent",
          text: "Cloning repos and loading tag context.",
        },
      ],
    };
    setTasks((prev) => [task, ...prev]);
    setSelectedTaskId(task.id);
  };

  return (
    <div className="flex h-full w-full overflow-hidden bg-(--color-background) text-gray-12">
      <PrototypeSidebar
        view={view}
        tasks={tasks}
        onNavigate={(next) => {
          setView(next);
        }}
        onNewTask={() => setNewTaskOpen(true)}
      />
      {view.kind === "home" || !TAGS_BY_ID[view.tagId] ? (
        <HomeView
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
          onOpenTag={openTag}
        />
      ) : (
        <TagView
          tag={TAGS_BY_ID[view.tagId]}
          tasks={tasks}
          selectedTaskId={selectedTaskId}
          onSelectTask={setSelectedTaskId}
          onOpenTag={openTag}
          onStartTask={startTask}
        />
      )}
      {selectedTask && (
        <TaskPanel
          task={selectedTask}
          onClose={() => setSelectedTaskId(null)}
          onOpenTag={openTag}
          onToggleTag={toggleTag}
        />
      )}
      <NewTaskDialog
        open={newTaskOpen}
        initialTagId={view.kind === "tag" ? view.tagId : undefined}
        onOpenChange={setNewTaskOpen}
        onStartTask={startTask}
      />
    </div>
  );
}

const TAGS_BY_ID = Object.fromEntries(TAGS.map((t) => [t.id, t]));
