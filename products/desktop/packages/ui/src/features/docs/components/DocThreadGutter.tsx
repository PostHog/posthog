import type { DocSchemas } from "@posthog/api-client/docs";
import type { Task } from "@posthog/shared/domain-types";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useState } from "react";
import {
  DocRefCardAction,
  DocRefCardActions,
  DocRefHover,
} from "../extensions/inline/DocRefCard";
import { useDiscussionMutations } from "../hooks/useDocDiscussions";
import { agentStateOf } from "../hooks/useDocThread";
import { lastLine, threadStanding } from "./DocThreadRow";
import { taskFor } from "./DocThreadsPanel";
import { VerdictPill } from "./DocWatchCard";

interface Pin {
  anchorKey: string;
  /** Distance from the top of the doc column, in pixels. */
  top: number;
}

/**
 * The marks in the doc's right margin, one for each place with a thread.
 *
 * They are measured against the column rather than drawn inside the line: a line
 * can be a list item or a quote, whose own box is narrower than the page, and a
 * mark that follows the text would sit in the middle of the page.
 */
export function DocThreadGutter({
  editor,
  docId,
  threads,
  tasks,
  onOpen,
}: {
  editor: Editor | null;
  docId: string;
  threads: DocSchemas.DiscussionThread[];
  tasks: Task[];
  onOpen: (anchorKey: string) => void;
}) {
  const [pins, setPins] = useState<Pin[]>([]);
  const watchMutation = useDiscussionMutations(docId).watch;

  const measure = useCallback(() => {
    if (!editor?.view.dom.isConnected) return;
    const container = editor.view.dom.getBoundingClientRect();
    const seen = new Set<string>();
    const next: Pin[] = [];

    const pin = (anchorKey: string, pos: number) => {
      if (!anchorKey || seen.has(anchorKey)) return;
      seen.add(anchorKey);
      try {
        const coords = editor.view.coordsAtPos(pos);
        next.push({ anchorKey, top: coords.top - container.top });
      } catch {
        // A position can be unresolvable for one frame after a remote step.
      }
    };

    editor.state.doc.descendants((node, pos) => {
      if (
        node.type.name === "dataRequest" ||
        node.type.name === "dataValue" ||
        node.type.name === "objectBlock"
      ) {
        const requestId = node.attrs?.requestId;
        if (typeof requestId === "string") pin(requestId, pos);
        return;
      }
      for (const mark of node.marks) {
        if (mark.type.name === "discussionAnchor") {
          pin(String(mark.attrs.anchorKey ?? ""), pos);
        }
      }
    });

    setPins((current) =>
      current.length === next.length &&
      current.every(
        (pin, index) =>
          pin.anchorKey === next[index].anchorKey &&
          Math.abs(pin.top - next[index].top) < 1,
      )
        ? current
        : next,
    );
  }, [editor]);

  useEffect(() => {
    if (!editor) return;
    measure();
    editor.on("update", measure);
    editor.on("selectionUpdate", measure);
    // Blocks change height when a chart loads or the window narrows, and the
    // marks have to follow their lines.
    const observer = new ResizeObserver(measure);
    observer.observe(editor.view.dom);
    return () => {
      editor.off("update", measure);
      editor.off("selectionUpdate", measure);
      observer.disconnect();
    };
  }, [editor, measure]);

  // A pin only shows once its thread exists: a mark whose thread was never
  // started, or was deleted, is just a highlight.
  const shown = pins
    .map((pin) => ({
      pin,
      thread: threads.find((thread) => thread.anchor_key === pin.anchorKey),
    }))
    .filter((entry) => entry.thread);
  if (shown.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-y-0 right-0 w-9">
      {shown.map(({ pin, thread }) => {
        if (!thread) return null;
        const standing = threadStanding(
          thread,
          agentStateOf(thread, taskFor(thread, tasks)),
        );
        const last = lastLine(thread);
        const replies = thread.replies.filter(
          (post) => post.author_kind !== "system",
        ).length;
        const openLabel =
          replies === 0
            ? "Open the thread"
            : `Open the thread, ${replies} ${replies === 1 ? "reply" : "replies"}`;
        const watch = thread.watch;
        return (
          <DocRefHover
            key={pin.anchorKey}
            side="left"
            nativeButton
            card={
              watch
                ? {
                    title: thread.anchor_text,
                    render: (close) => (
                      <div className="w-64 p-2.5">
                        <div className="flex items-start gap-2">
                          <VerdictPill watch={watch} />
                          <span className="line-clamp-3 min-w-0 flex-1 whitespace-normal text-(--gray-11) text-[11.5px] leading-snug">
                            {watch.verdict.reason || last.text}
                          </span>
                        </div>
                        <DocRefCardActions>
                          <DocRefCardAction
                            onSelect={() => {
                              onOpen(pin.anchorKey);
                              close();
                            }}
                          >
                            {openLabel}
                          </DocRefCardAction>
                          {watch.status === "active" && watch.brief ? (
                            <DocRefCardAction
                              onSelect={() => {
                                watchMutation.mutate({
                                  threadId: thread.id,
                                  body: { action: "check" },
                                });
                                close();
                              }}
                            >
                              Check now
                            </DocRefCardAction>
                          ) : null}
                          {watch.stopped_reason === "verdict" ? null : (
                            <DocRefCardAction
                              onSelect={() => {
                                watchMutation.mutate({
                                  threadId: thread.id,
                                  body: {
                                    action:
                                      watch.status === "active"
                                        ? "stop"
                                        : "resume",
                                  },
                                });
                                close();
                              }}
                            >
                              {watch.status === "active"
                                ? "Stop watching"
                                : "Watch again"}
                            </DocRefCardAction>
                          )}
                        </DocRefCardActions>
                      </div>
                    ),
                  }
                : {
                    title: last.who,
                    meta: (
                      <span className="line-clamp-3 whitespace-normal text-(--gray-11) text-[11.5px] leading-snug">
                        {last.text}
                      </span>
                    ),
                    action: {
                      label: openLabel,
                      onSelect: () => onOpen(pin.anchorKey),
                    },
                  }
            }
            trigger={
              <button
                type="button"
                aria-label="Open the thread for this line"
                onClick={() => onOpen(pin.anchorKey)}
                style={{ top: `${pin.top + 2}px` }}
                className="pointer-events-auto absolute right-0 grid size-6 cursor-pointer place-items-center rounded-(--radius-2) transition-colors hover:bg-(--gray-4)"
              >
                <DocMark
                  variant={standing.variant}
                  state={standing.state}
                  size={16}
                  count={replies}
                />
              </button>
            }
          />
        );
      })}
    </div>
  );
}
