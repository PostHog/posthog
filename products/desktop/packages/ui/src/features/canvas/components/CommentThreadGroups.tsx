import {
  CaretDownIcon,
  ChatCircleIcon,
  GitPullRequestIcon,
  GlobeIcon,
} from "@phosphor-icons/react";
import { Button, cn } from "@posthog/quill";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import type {
  SourceKind,
  TaskCommentThread,
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
export function SourceIcon({
  kind,
  label,
  size = 12,
}: {
  kind: SourceKind;
  label: string;
  size?: number;
}) {
  switch (kind) {
    case "pr":
      return (
        <GitPullRequestIcon size={size} className="shrink-0 text-gray-11" />
      );
    case "canvas":
      return iconForTemplate("", { size, className: "text-violet-9" });
    case "task":
      return <ChatCircleIcon size={size} className="shrink-0 text-gray-11" />;
    case "preview":
    case "browser":
      return <GlobeIcon size={size} className="shrink-0 text-gray-11" />;
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
  const groups = useMemo(
    () => [...Map.groupBy(threads, (thread) => thread.sourceKey).values()],
    [threads],
  );
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

  return (
    <div data-comment-thread-list>
      {groups.map((group) => {
        const { sourceKey, sourceLabel, sourceKind } = group[0];
        const open = !collapsed.has(sourceKey);
        return (
          <section key={sourceKey} aria-label={sourceLabel}>
            {grouped && (
              <Button
                variant="default"
                size="sm"
                aria-expanded={open}
                title={sourceLabel}
                data-thread-focus="group"
                className="sticky top-0 z-10 h-8 w-full justify-start gap-1.5 rounded-none border-border/70 border-b bg-background px-3 text-muted-foreground hover:bg-background hover:text-foreground"
                onClick={() => toggle(sourceKey)}
                onKeyDown={moveThreadFocus}
              >
                <CaretDownIcon
                  className={cn(
                    "shrink-0 text-muted-foreground transition-transform",
                    !open && "-rotate-90",
                  )}
                />
                <SourceIcon kind={sourceKind} label={sourceLabel} />
                <span className="min-w-0 truncate">{sourceLabel}</span>
                <span className="ml-auto shrink-0 pl-2 font-normal text-muted-foreground tabular-nums">
                  {group.length}
                </span>
              </Button>
            )}
            {(open || !grouped) && group.map(renderThread)}
          </section>
        );
      })}
    </div>
  );
}
