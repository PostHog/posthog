import type { DocSchemas } from "@posthog/api-client/docs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useState } from "react";
import { agentStateOf } from "../hooks/useDocThread";
import { lastLine, threadStanding } from "./DocThreadRow";
import { taskFor } from "./DocThreadsPanel";

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
  threads,
  tasks,
  onOpen,
}: {
  editor: Editor | null;
  threads: DocSchemas.DiscussionThread[];
  tasks: Task[];
  onOpen: (anchorKey: string) => void;
}) {
  const [pins, setPins] = useState<Pin[]>([]);

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
        return (
          <Tooltip key={pin.anchorKey}>
            <TooltipTrigger
              render={
                <button
                  type="button"
                  aria-label="Open the thread for this line"
                  onClick={() => onOpen(pin.anchorKey)}
                  style={{ top: `${pin.top + 2}px` }}
                  className="pointer-events-auto absolute right-0 grid size-6 cursor-pointer place-items-center rounded-(--radius-2) transition-colors hover:bg-(--gray-4)"
                />
              }
            >
              <DocMark
                variant={standing.variant}
                state={standing.state}
                size={16}
                count={replies}
              />
            </TooltipTrigger>
            <TooltipContent side="left" className="max-w-xs">
              <span className="block whitespace-normal font-medium">
                {last.who}
              </span>
              <span className="line-clamp-3 block whitespace-normal text-(--gray-5) leading-snug">
                {last.text}
              </span>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
