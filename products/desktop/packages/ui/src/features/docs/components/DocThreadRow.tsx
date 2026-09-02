import type { DocSchemas } from "@posthog/api-client/docs";
import { cn } from "@posthog/quill";
import { formatRelativeTimeShort } from "@posthog/shared";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { DocMark, type DocMarkState } from "@posthog/ui/primitives/DocMark";
import { personName } from "./DocPostRow";
import { watchMarkState } from "./DocWatchCard";

/** How a thread stands, read off the thread and its task. */
export interface ThreadStanding {
  variant: "agent" | "discussion";
  state: DocMarkState;
}

export function threadStanding(
  thread: DocSchemas.DiscussionThread,
  taskState: "working" | "waiting" | "failed" | "done" | null,
): ThreadStanding {
  if (thread.task_id || thread.kind === "watch") {
    if (
      taskState === "working" ||
      taskState === "waiting" ||
      taskState === "failed"
    ) {
      return { variant: "agent", state: taskState };
    }
    if (thread.watch) {
      return { variant: "agent", state: watchMarkState(thread.watch) };
    }
    return { variant: "agent", state: thread.resolved ? "handled" : "still" };
  }
  return { variant: "discussion", state: thread.resolved ? "handled" : "open" };
}

/**
 * A post as one line: no markup, no query. A cited query reads as its label,
 * or as "the query" when it had none.
 */
export function plainLine(content: string): string {
  return content
    .replace(
      /<hogql\b[^>]*?(?:label|title)="([^"]*)"[^>]*>[\s\S]*?<\/hogql>/gi,
      "$1",
    )
    .replace(/<hogql\b[^>]*>[\s\S]*?<\/hogql>/gi, "the query")
    .replace(/<(\w+)\b[^>]*>([^<]*)<\/\1>/g, "$2")
    .replace(/\*\*|`/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** The last thing said, for a row that has one line to say it in. */
export function lastLine(thread: DocSchemas.DiscussionThread): {
  who: string;
  text: string;
  at: string;
} {
  const posts = [thread, ...thread.replies].filter(
    (post) => post.author_kind !== "system",
  );
  const last = posts[posts.length - 1] ?? thread;
  return {
    who: last.author_kind === "agent" ? "Agent" : personName(last.created_by),
    text: plainLine(last.content),
    at: last.created_at,
  };
}

/**
 * One thread in the list: what it hangs off, the last thing said, who is in
 * it. The mark on the left is the same one the margin shows.
 */
export function DocThreadRow({
  thread,
  standing,
  selected,
  onOpen,
}: {
  thread: DocSchemas.DiscussionThread;
  standing: ThreadStanding;
  selected: boolean;
  onOpen: () => void;
}) {
  const last = lastLine(thread);
  const people = new Map<string, DocSchemas.DocPerson>();
  for (const post of [thread, ...thread.replies]) {
    if (post.created_by) people.set(post.created_by.uuid, post.created_by);
  }
  const replyCount = thread.replies.filter(
    (post) => post.author_kind !== "system",
  ).length;

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "flex w-full cursor-pointer gap-2.5 rounded-(--radius-3) px-2.5 py-2 text-left transition-colors hover:bg-(--gray-3)",
        selected && "bg-(--gray-3)",
        thread.resolved && "opacity-70",
      )}
    >
      <DocMark
        variant={standing.variant}
        state={standing.state}
        size={14}
        className="mt-[3px]"
      />
      <span className="min-w-0 flex-1">
        <span
          className="doc-thread-quote block"
          data-kind={thread.kind}
          style={{ WebkitLineClamp: 1 }}
        >
          {thread.anchor_text || "a place in the doc"}
        </span>
        <span className="mt-1 block truncate text-(--gray-12) text-[13px]">
          <span className="font-medium">{last.who}</span>
          <span className="text-(--gray-11)"> {last.text}</span>
        </span>
        <span className="mt-1 flex items-center gap-2 text-(--gray-9) text-[11px]">
          <span className="-space-x-1 flex">
            {[...people.values()].slice(0, 4).map((person) => (
              <UserAvatar key={person.uuid} user={person} size="xs" />
            ))}
          </span>
          {replyCount > 0 ? (
            <span>
              {replyCount === 1 ? "1 reply" : `${replyCount} replies`}
            </span>
          ) : null}
          <span className="ml-auto">{formatRelativeTimeShort(last.at)}</span>
        </span>
      </span>
    </button>
  );
}
