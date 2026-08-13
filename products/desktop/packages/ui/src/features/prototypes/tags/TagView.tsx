import {
  BookOpenIcon,
  GitBranchIcon,
  PaperPlaneRightIcon,
  RobotIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  HOME_SECTION_LABELS,
  type PrototypeTag,
  type PrototypeTask,
  STATUS_ORDER,
} from "@posthog/ui/features/prototypes/tags/mockData";
import {
  FaceStack,
  SectionLabel,
  TagGlyph,
} from "@posthog/ui/features/prototypes/tags/shared";
import { TaskRow } from "@posthog/ui/features/prototypes/tags/TaskRow";
import { useState } from "react";

function MetadataPill({
  icon,
  label,
  tooltip,
}: {
  icon: React.ReactNode;
  label: string;
  tooltip: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="inline-flex cursor-default items-center gap-1.5 rounded-md border border-border bg-gray-2 px-2 py-1 text-[11px] text-gray-11">
            {icon}
            {label}
          </span>
        }
      />
      <TooltipContent side="bottom">{tooltip}</TooltipContent>
    </Tooltip>
  );
}

export function TagView({
  tag,
  tasks,
  selectedTaskId,
  onSelectTask,
  onOpenTag,
  onStartTask,
}: {
  tag: PrototypeTag;
  tasks: PrototypeTask[];
  selectedTaskId: string | null;
  onSelectTask: (id: string) => void;
  onOpenTag: (tagId: string) => void;
  onStartTask: (title: string, tagIds: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const tagTasks = tasks.filter((t) => t.tagIds.includes(tag.id));

  const start = () => {
    const title = draft.trim();
    if (!title) return;
    onStartTask(title, [tag.id]);
    setDraft("");
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <div className="shrink-0 border-border border-b px-5 pt-4 pb-3">
        <div className="flex items-center gap-2.5">
          <TagGlyph tag={tag} size={18} />
          <h1 className="font-semibold text-[17px] text-gray-12">{tag.name}</h1>
          <div className="flex-1" />
          <FaceStack personIds={tag.memberIds} online={tag.onlineIds} max={5} />
          <span className="text-[11px] text-gray-10">
            {tag.onlineIds.length} online
          </span>
        </div>
        <p className="mt-1 text-[12px] text-gray-10">{tag.description}</p>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {tag.repos.map((repo) => (
            <MetadataPill
              key={repo}
              icon={<GitBranchIcon size={12} />}
              label={repo}
              tooltip="Cloned automatically when a task starts under this tag"
            />
          ))}
          {tag.context.map((doc) => (
            <MetadataPill
              key={doc}
              icon={<BookOpenIcon size={12} />}
              label={doc}
              tooltip="Attached to the agent's context on every new task"
            />
          ))}
          <MetadataPill
            icon={<RobotIcon size={12} />}
            label={tag.agentPreset}
            tooltip="Default agent preset for this tag"
          />
        </div>
      </div>

      <div className="@container min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {STATUS_ORDER.map((status) => {
          const sectionTasks = tagTasks.filter((t) => t.status === status);
          if (sectionTasks.length === 0) return null;
          return (
            <div key={status}>
              <SectionLabel count={sectionTasks.length}>
                {HOME_SECTION_LABELS[status]}
              </SectionLabel>
              {sectionTasks.map((task) => (
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
      </div>

      <div className="shrink-0 border-border border-t p-3">
        <div className="rounded-lg border border-border bg-gray-2 focus-within:border-gray-7">
          <input
            className="w-full bg-transparent px-3 pt-2.5 pb-1 text-[13px] text-gray-12 outline-none placeholder:text-gray-9"
            placeholder={`Start an agent in ${tag.name}…`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") start();
            }}
          />
          <div className="flex items-center gap-1.5 px-3 pb-2">
            <span className="text-[10px] text-gray-9">
              Starts with {tag.repos.join(" + ")} · {tag.context.join(", ")}
            </span>
            <div className="flex-1" />
            <Button
              size="sm"
              variant="primary"
              disabled={!draft.trim()}
              onClick={start}
            >
              <PaperPlaneRightIcon size={12} />
              Start agent
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
