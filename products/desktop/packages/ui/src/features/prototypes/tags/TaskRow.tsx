import {
  GitBranchIcon,
  GitMergeIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import {
  type PrototypeTask,
  TAGS,
} from "@posthog/ui/features/prototypes/tags/mockData";
import {
  FaceStack,
  StatusDot,
  TagChip,
} from "@posthog/ui/features/prototypes/tags/shared";

export function TaskRow({
  task,
  selected,
  hideTagId,
  onSelect,
  onTagClick,
}: {
  task: PrototypeTask;
  selected: boolean;
  /** In a tag view, the scoping tag is implied — don't repeat its chip */
  hideTagId?: string;
  onSelect: () => void;
  onTagClick: (tagId: string) => void;
}) {
  const tags = TAGS.filter(
    (t) => task.tagIds.includes(t.id) && t.id !== hideTagId,
  );
  const live = task.status === "running" || task.status === "needs_input";
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "group flex w-full cursor-pointer items-center gap-2.5 rounded-md border border-transparent px-2 py-1.5 text-left transition-colors",
        selected ? "border-border bg-gray-3" : "hover:bg-gray-2",
      )}
    >
      <StatusDot status={task.status} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "truncate text-[13px]",
              task.unread
                ? "font-semibold text-gray-12"
                : "font-medium text-gray-12",
              task.status === "done" && "text-gray-10",
            )}
          >
            {task.title}
          </span>
          {task.unread && (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--primary)" />
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-gray-10">
          <span
            className={cn("truncate", live && "text-gray-11")}
            style={
              task.status === "needs_input"
                ? { color: "var(--amber-11)" }
                : undefined
            }
          >
            {task.statusDetail}
          </span>
        </div>
      </div>
      <div className="@lg:flex hidden items-center gap-1">
        {tags.map((tag) => (
          <TagChip key={tag.id} tag={tag} onClick={() => onTagClick(tag.id)} />
        ))}
      </div>
      {task.prUrl && (
        <span
          className="@md:flex hidden items-center gap-1 text-[11px]"
          style={{
            color:
              task.prState === "merged"
                ? "var(--purple-11)"
                : task.prState === "draft"
                  ? "var(--gray-10)"
                  : "var(--green-11)",
          }}
        >
          {task.prState === "merged" ? (
            <GitMergeIcon size={12} />
          ) : (
            <GitPullRequestIcon size={12} />
          )}
          {task.prUrl}
        </span>
      )}
      <span className="@xl:flex hidden items-center gap-1 text-[11px] text-gray-9">
        <GitBranchIcon size={11} />
        {task.repo.split("/")[1]}
      </span>
      <FaceStack personIds={task.participantIds} />
      <span className="w-12 shrink-0 text-right text-[11px] text-gray-9">
        {task.updated}
      </span>
    </button>
  );
}
