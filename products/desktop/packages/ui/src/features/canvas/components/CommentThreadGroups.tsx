import {
  CaretDownIcon,
  ChatCircleIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import {
  groupThreadsBySource,
  type SourceKind,
  type TaskCommentThread,
} from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { moveThreadFocus } from "@posthog/ui/features/sessions/components/threadListFocus";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import {
  type ReactElement,
  type ReactNode,
  useLayoutEffect,
  useMemo,
  useState,
} from "react";

/** The icon a source shows wherever it's named — the card label and the
 *  filter menu — so the two always agree. */
export function sourceIcon(kind: SourceKind, label: string, size = 12) {
  switch (kind) {
    case "pr":
      return (
        <GitPullRequestIcon size={size} className="shrink-0 text-gray-11" />
      );
    case "canvas":
      return iconForTemplate("", { size, className: "text-violet-9" });
    case "task":
      return <ChatCircleIcon size={size} className="shrink-0 text-gray-11" />;
    default:
      return <FileIcon filename={label} size={size} />;
  }
}

export function CommentThreadGroups({
  threads,
  grouped,
  revealThreadId,
  renderThread,
}: {
  threads: TaskCommentThread[];
  grouped: boolean;
  revealThreadId?: string | null;
  renderThread: (thread: TaskCommentThread) => ReactNode;
}): ReactElement {
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const groups = useMemo(() => groupThreadsBySource(threads), [threads]);
  const revealKey = revealThreadId
    ? threads.find((thread) => thread.id === revealThreadId)?.sourceKey
    : undefined;

  useLayoutEffect(() => {
    if (!revealKey) return;
    setCollapsed((current) => {
      if (!current.has(revealKey)) return current;
      const next = new Set(current);
      next.delete(revealKey);
      return next;
    });
  }, [revealKey]);

  const toggle = (key: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  if (!grouped) {
    return <div data-comment-thread-list>{threads.map(renderThread)}</div>;
  }

  return (
    <div data-comment-thread-list>
      {groups.map((group) => {
        const open = !collapsed.has(group.key);
        return (
          <section key={group.key} aria-label={group.label}>
            <Button
              variant="default"
              size="sm"
              aria-expanded={open}
              title={group.label}
              data-thread-focus="group"
              className="sticky top-0 z-10 h-8 w-full justify-start gap-1.5 rounded-none border-border/70 border-b bg-background px-3 text-muted-foreground hover:bg-background hover:text-foreground"
              onClick={() => toggle(group.key)}
              onKeyDown={moveThreadFocus}
            >
              <CaretDownIcon
                className={cn(
                  "shrink-0 text-muted-foreground transition-transform",
                  !open && "-rotate-90",
                )}
              />
              {sourceIcon(group.kind, group.label)}
              <span className="min-w-0 truncate">{group.label}</span>
              <span className="ml-auto shrink-0 pl-2 font-normal text-muted-foreground tabular-nums">
                {group.threads.length}
              </span>
            </Button>
            {open && group.threads.map(renderThread)}
          </section>
        );
      })}
    </div>
  );
}
