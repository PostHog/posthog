import {
  cn,
  Tabs,
  TabsList,
  TabsTrigger,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import {
  HOME_SECTION_LABELS,
  type PrototypeTask,
  type PrototypeTaskStatus,
  STATUS_ORDER,
  TAGS,
} from "@posthog/ui/features/prototypes/tags/mockData";
import { SectionLabel } from "@posthog/ui/features/prototypes/tags/shared";
import { TaskRow } from "@posthog/ui/features/prototypes/tags/TaskRow";
import { useState } from "react";

type HomeFilter = "all" | "mine" | "running" | "needs_you";
type GroupBy = "status" | "tag";

function applyFilter(
  tasks: PrototypeTask[],
  filter: HomeFilter,
): PrototypeTask[] {
  switch (filter) {
    case "mine":
      return tasks.filter((t) => t.participantIds.includes("you"));
    case "running":
      return tasks.filter(
        (t) => t.status === "running" || t.status === "queued",
      );
    case "needs_you":
      return tasks.filter(
        (t) =>
          (t.status === "needs_input" || t.unread) &&
          t.participantIds.includes("you"),
      );
    default:
      return tasks;
  }
}

export function HomeView({
  tasks,
  selectedTaskId,
  onSelectTask,
  onOpenTag,
}: {
  tasks: PrototypeTask[];
  selectedTaskId: string | null;
  onSelectTask: (id: string) => void;
  onOpenTag: (tagId: string) => void;
}) {
  const [filter, setFilter] = useState<HomeFilter>("all");
  const [groupBy, setGroupBy] = useState<GroupBy>("status");

  const filtered = applyFilter(tasks, filter);
  const runningCount = tasks.filter((t) => t.status === "running").length;
  const needsYouCount = tasks.filter(
    (t) => t.status === "needs_input" && t.participantIds.includes("you"),
  ).length;

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <div className="shrink-0 border-border border-b px-5 pt-4 pb-0">
        <div className="flex items-baseline gap-3">
          <h1 className="font-semibold text-[17px] text-gray-12">Home</h1>
          <span className="text-[12px] text-gray-10">
            {runningCount} agents running
            {needsYouCount > 0 && (
              <>
                {" · "}
                <span className="text-(--amber-11)">
                  {needsYouCount} waiting on you
                </span>
              </>
            )}
          </span>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <Tabs
            value={filter}
            onValueChange={(v) => setFilter(v as HomeFilter)}
          >
            <TabsList variant="line" className="h-auto gap-0.5">
              <TabsTrigger value="all" className="px-2.5 py-2 text-[13px]">
                All
              </TabsTrigger>
              <TabsTrigger
                value="needs_you"
                className="px-2.5 py-2 text-[13px]"
              >
                Needs you
              </TabsTrigger>
              <TabsTrigger value="running" className="px-2.5 py-2 text-[13px]">
                Running
              </TabsTrigger>
              <TabsTrigger value="mine" className="px-2.5 py-2 text-[13px]">
                Involving me
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <ToggleGroup
            value={[groupBy]}
            onValueChange={(v) => {
              const next = v[0] as GroupBy | undefined;
              if (next) setGroupBy(next);
            }}
            className="mb-1"
          >
            <ToggleGroupItem value="status" className="px-2 text-[11px]">
              By status
            </ToggleGroupItem>
            <ToggleGroupItem value="tag" className="px-2 text-[11px]">
              By tag
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>

      <div className="@container min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {groupBy === "status"
          ? STATUS_ORDER.map((status) => (
              <StatusSection
                key={status}
                status={status}
                tasks={filtered.filter((t) => t.status === status)}
                selectedTaskId={selectedTaskId}
                onSelectTask={onSelectTask}
                onOpenTag={onOpenTag}
              />
            ))
          : TAGS.map((tag) => {
              const tagTasks = filtered.filter((t) =>
                t.tagIds.includes(tag.id),
              );
              if (tagTasks.length === 0) return null;
              return (
                <div key={tag.id}>
                  <SectionLabel count={tagTasks.length}>
                    <button
                      type="button"
                      className={cn("uppercase hover:underline")}
                      style={{ color: `var(--${tag.hue}-11)` }}
                      onClick={() => onOpenTag(tag.id)}
                    >
                      {tag.name}
                    </button>
                  </SectionLabel>
                  {tagTasks.map((task) => (
                    <TaskRow
                      key={task.id}
                      task={task}
                      selected={task.id === selectedTaskId}
                      hideTagId={tag.id}
                      onSelect={() => onSelectTask(task.id)}
                      onTagClick={onOpenTag}
                    />
                  ))}
                </div>
              );
            })}
        {filtered.length === 0 && (
          <div className="px-2 py-10 text-center text-[13px] text-gray-10">
            Nothing here — switch filters or start a new task.
          </div>
        )}
      </div>
    </div>
  );
}

function StatusSection({
  status,
  tasks,
  selectedTaskId,
  onSelectTask,
  onOpenTag,
}: {
  status: PrototypeTaskStatus;
  tasks: PrototypeTask[];
  selectedTaskId: string | null;
  onSelectTask: (id: string) => void;
  onOpenTag: (tagId: string) => void;
}) {
  if (tasks.length === 0) return null;
  return (
    <div>
      <SectionLabel count={tasks.length}>
        {HOME_SECTION_LABELS[status]}
      </SectionLabel>
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          selected={task.id === selectedTaskId}
          onSelect={() => onSelectTask(task.id)}
          onTagClick={onOpenTag}
        />
      ))}
    </div>
  );
}
