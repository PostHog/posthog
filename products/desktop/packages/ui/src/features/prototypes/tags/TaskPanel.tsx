import {
  GitBranchIcon,
  GitMergeIcon,
  GitPullRequestIcon,
  PlusIcon,
  RobotIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Progress,
  Separator,
} from "@posthog/quill";
import {
  type PrototypeTask,
  personById,
  STATUS_META,
  TAGS,
} from "@posthog/ui/features/prototypes/tags/mockData";
import {
  FaceStack,
  StatusDot,
  TagChip,
} from "@posthog/ui/features/prototypes/tags/shared";

export function TaskPanel({
  task,
  onClose,
  onOpenTag,
  onToggleTag,
}: {
  task: PrototypeTask;
  onClose: () => void;
  onOpenTag: (tagId: string) => void;
  onToggleTag: (taskId: string, tagId: string) => void;
}) {
  const taskTags = TAGS.filter((t) => task.tagIds.includes(t.id));
  const availableTags = TAGS.filter((t) => !task.tagIds.includes(t.id));
  const meta = STATUS_META[task.status];

  return (
    <div className="flex h-full w-80 shrink-0 flex-col border-border border-l bg-chrome">
      <div className="flex items-start gap-2 px-4 pt-3 pb-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusDot status={task.status} />
            <span className="text-[11px] text-gray-10">{meta.label}</span>
          </div>
          <h2 className="mt-1 font-semibold text-[14px] text-gray-12 leading-snug">
            {task.title}
          </h2>
        </div>
        <button
          type="button"
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded text-gray-9 hover:bg-gray-3 hover:text-gray-12"
          onClick={onClose}
          aria-label="Close panel"
        >
          <XIcon size={14} />
        </button>
      </div>

      <div className="flex flex-col gap-3 overflow-y-auto px-4 pb-4">
        {task.status === "running" && task.progress !== undefined && (
          <div>
            <Progress value={task.progress} className="h-1" />
            <p className="mt-1.5 text-[11px] text-gray-10">
              {task.statusDetail}
            </p>
          </div>
        )}
        {task.status === "needs_input" && (
          <div
            className="rounded-md border px-3 py-2 text-[12px]"
            style={{
              borderColor: "var(--amber-6)",
              background: "var(--amber-2)",
              color: "var(--amber-11)",
            }}
          >
            {task.statusDetail}
            <div className="mt-2 flex gap-1.5">
              <Button size="sm" variant="primary">
                Answer agent
              </Button>
              <Button size="sm" variant="outline">
                Open session
              </Button>
            </div>
          </div>
        )}

        <div>
          <div className="mb-1.5 font-semibold text-[11px] text-gray-9 uppercase tracking-wide">
            Tags
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {taskTags.map((tag) => (
              <TagChip
                key={tag.id}
                tag={tag}
                size="md"
                onClick={() => onOpenTag(tag.id)}
                onRemove={
                  task.tagIds.length > 1
                    ? () => onToggleTag(task.id, tag.id)
                    : undefined
                }
              />
            ))}
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <button
                    type="button"
                    className="flex h-5 w-5 items-center justify-center rounded-full border border-border border-dashed text-gray-9 hover:bg-gray-3 hover:text-gray-12"
                    aria-label="Add tag"
                  >
                    <PlusIcon size={11} />
                  </button>
                }
              />
              <DropdownMenuContent align="start">
                {availableTags.map((tag) => (
                  <DropdownMenuItem
                    key={tag.id}
                    onClick={() => onToggleTag(task.id, tag.id)}
                  >
                    <span
                      className="mr-1.5 inline-block h-2 w-2 rounded-full"
                      style={{ background: `var(--${tag.hue}-9)` }}
                    />
                    {tag.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          <p className="mt-1.5 text-[10px] text-gray-9">
            A task can live in several tags — everyone following any of them
            sees it.
          </p>
        </div>

        <Separator />

        <div className="flex flex-col gap-2 text-[12px]">
          <div className="flex items-center gap-2 text-gray-11">
            <GitBranchIcon size={13} className="text-gray-9" />
            {task.repo}
            {task.branch && (
              <span className="rounded bg-gray-3 px-1.5 py-px font-mono text-[10px] text-gray-10">
                {task.branch}
              </span>
            )}
          </div>
          {task.prUrl && (
            <div className="flex items-center gap-2 text-gray-11">
              {task.prState === "merged" ? (
                <GitMergeIcon size={13} style={{ color: "var(--purple-11)" }} />
              ) : (
                <GitPullRequestIcon
                  size={13}
                  style={{ color: "var(--green-11)" }}
                />
              )}
              Pull request {task.prUrl}
              <span className="text-gray-9">({task.prState})</span>
            </div>
          )}
          <div className="flex items-center gap-2 text-gray-11">
            <RobotIcon size={13} className="text-gray-9" />
            Agent session
            <Button size="sm" variant="outline" className="ml-auto">
              Open
            </Button>
          </div>
        </div>

        <Separator />

        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="font-semibold text-[11px] text-gray-9 uppercase tracking-wide">
              People
            </span>
            <FaceStack personIds={task.participantIds} max={5} />
          </div>
          <div className="mt-3 mb-1.5 font-semibold text-[11px] text-gray-9 uppercase tracking-wide">
            Activity
          </div>
          <div className="flex flex-col gap-2.5 border-border border-l pl-3">
            {task.activity.map((entry) => (
              <div key={`${entry.time}-${entry.text}`} className="text-[11px]">
                <span className="text-gray-9">
                  {entry.actor === "agent"
                    ? "Agent"
                    : personById(entry.actor).name}
                  {" · "}
                  {entry.time} ago
                </span>
                <p className="mt-0.5 text-[12px] text-gray-11 leading-snug">
                  {entry.text}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
