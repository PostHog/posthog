import {
  HouseIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  Kbd,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  PEOPLE,
  type PrototypeTag,
  type PrototypeTask,
  TAGS,
} from "@posthog/ui/features/prototypes/tags/mockData";
import { FaceStack } from "@posthog/ui/features/prototypes/tags/shared";
import type { PrototypeView } from "@posthog/ui/features/prototypes/tags/TagsPrototype";

function TagRow({
  tag,
  tasks,
  active,
  onClick,
}: {
  tag: PrototypeTag;
  tasks: PrototypeTask[];
  active: boolean;
  onClick: () => void;
}) {
  const tagTasks = tasks.filter((t) => t.tagIds.includes(tag.id));
  const running = tagTasks.filter((t) => t.status === "running").length;
  const needsYou = tagTasks.filter((t) => t.status === "needs_input").length;
  const unread = tagTasks.filter((t) => t.unread).length;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors",
        active ? "bg-gray-4 text-gray-12" : "text-gray-11 hover:bg-gray-3",
      )}
    >
      <span
        className="inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ background: `var(--${tag.hue}-9)` }}
      />
      <span className="min-w-0 flex-1 truncate text-[13px]">{tag.name}</span>
      {tag.onlineIds.length > 0 && (
        <FaceStack personIds={tag.onlineIds} online={tag.onlineIds} max={2} />
      )}
      {running > 0 && (
        <Tooltip>
          <TooltipTrigger
            render={
              <span className="flex items-center gap-1 text-(--green-11) text-[11px]">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-(--green-9)" />
                {running}
              </span>
            }
          />
          <TooltipContent side="right">
            {running} agent{running > 1 ? "s" : ""} running
          </TooltipContent>
        </Tooltip>
      )}
      {(needsYou > 0 || unread > 0) && (
        <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-(--primary) px-1 font-semibold text-(--primary-foreground) text-[10px]">
          {needsYou + unread}
        </span>
      )}
    </button>
  );
}

export function PrototypeSidebar({
  view,
  tasks,
  onNavigate,
  onNewTask,
}: {
  view: PrototypeView;
  tasks: PrototypeTask[];
  onNavigate: (view: PrototypeView) => void;
  onNewTask: () => void;
}) {
  const needsYou = tasks.filter(
    (t) => t.status === "needs_input" || t.unread,
  ).length;
  const online = PEOPLE.filter((p) => !p.isViewer).slice(0, 4);
  return (
    <div className="flex h-full w-60 shrink-0 flex-col border-border border-r bg-chrome">
      <div className="flex items-center gap-1 px-2 pt-2 pb-1">
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                onClick={() => onNavigate({ kind: "home" })}
                className={cn(
                  "relative flex h-7 w-7 items-center justify-center rounded-md transition-colors",
                  view.kind === "home"
                    ? "bg-gray-4 text-gray-12"
                    : "text-gray-10 hover:bg-gray-3 hover:text-gray-12",
                )}
                aria-label="Home"
              >
                <HouseIcon
                  size={16}
                  weight={view.kind === "home" ? "fill" : "regular"}
                />
                {needsYou > 0 && view.kind !== "home" && (
                  <span className="absolute top-0.5 right-0.5 h-1.5 w-1.5 rounded-full bg-(--primary)" />
                )}
              </button>
            }
          />
          <TooltipContent side="bottom">
            Home — everything across tags <Kbd>⌘1</Kbd>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                className="flex h-7 w-7 items-center justify-center rounded-md text-gray-10 transition-colors hover:bg-gray-3 hover:text-gray-12"
                aria-label="Search"
              >
                <MagnifyingGlassIcon size={16} />
              </button>
            }
          />
          <TooltipContent side="bottom">
            Search <Kbd>⌘K</Kbd>
          </TooltipContent>
        </Tooltip>
        <div className="flex-1" />
        <Button size="sm" variant="primary" onClick={onNewTask}>
          <PlusIcon size={13} />
          New task
        </Button>
      </div>

      <div className="mt-2 flex items-center px-3 pb-1">
        <span className="font-semibold text-[11px] text-gray-9 uppercase tracking-wide">
          Tags
        </span>
        <div className="flex-1" />
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                type="button"
                className="flex h-5 w-5 items-center justify-center rounded text-gray-9 hover:bg-gray-3 hover:text-gray-12"
                aria-label="New tag"
              >
                <PlusIcon size={12} />
              </button>
            }
          />
          <TooltipContent side="right">New tag</TooltipContent>
        </Tooltip>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2">
        {TAGS.map((tag) => (
          <TagRow
            key={tag.id}
            tag={tag}
            tasks={tasks}
            active={view.kind === "tag" && view.tagId === tag.id}
            onClick={() => onNavigate({ kind: "tag", tagId: tag.id })}
          />
        ))}
        <div className="px-2 pt-3 text-[11px] text-gray-9 leading-relaxed">
          Tags are flat and many-to-many: a task can carry several, and each tag
          brings its own repos and context to new tasks.
        </div>
      </div>

      <div className="flex items-center gap-2 border-border border-t px-3 py-2">
        <FaceStack
          personIds={online.map((p) => p.id)}
          online={online.slice(0, 3).map((p) => p.id)}
          max={4}
        />
        <span className="text-[11px] text-gray-10">3 teammates online</span>
      </div>
    </div>
  );
}
