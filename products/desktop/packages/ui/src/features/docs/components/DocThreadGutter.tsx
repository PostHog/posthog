import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import { AgentMark } from "@posthog/ui/primitives/AgentMark";
import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useState } from "react";
import { THREAD_ATTRIBUTE } from "../extensions/ThreadGutter";

interface ThreadPin {
  taskId: string;
  /** Distance from the top of the doc column, in pixels. */
  top: number;
}

/**
 * The marks in the doc's right margin, one for each line with an agent thread.
 *
 * They are measured against the column rather than drawn inside the line: a line
 * can be a list item or a quote, whose own box is narrower than the page, and a
 * mark that follows the text would sit in the middle of the page.
 */
export function DocThreadGutter({
  editor,
  onOpen,
}: {
  editor: Editor | null;
  onOpen: (taskId: string) => void;
}) {
  const [pins, setPins] = useState<ThreadPin[]>([]);

  const measure = useCallback(() => {
    if (!editor?.view.dom.isConnected) return;
    const container = editor.view.dom.getBoundingClientRect();
    const next: ThreadPin[] = [];

    editor.state.doc.descendants((node, pos) => {
      const taskId = node.attrs?.[THREAD_ATTRIBUTE];
      if (typeof taskId !== "string" || !taskId) return;
      try {
        const coords = editor.view.coordsAtPos(pos + 1);
        next.push({ taskId, top: coords.top - container.top });
      } catch {
        // A position can be unresolvable for one frame after a remote step.
      }
    });

    setPins((current) =>
      current.length === next.length &&
      current.every(
        (pin, index) =>
          pin.taskId === next[index].taskId &&
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

  if (pins.length === 0) return null;

  return (
    <div
      aria-hidden={false}
      className="pointer-events-none absolute inset-y-0 right-0 w-9"
    >
      {pins.map((pin) => (
        <Tooltip key={`${pin.taskId}-${Math.round(pin.top)}`}>
          <TooltipTrigger
            render={
              <button
                type="button"
                aria-label="Open the agent thread for this line"
                onClick={() => onOpen(pin.taskId)}
                style={{ top: `${pin.top}px` }}
                className="pointer-events-auto absolute right-0 grid size-[22px] cursor-pointer place-items-center rounded-(--radius-2) bg-(--primary-a3) text-(--primary) transition-colors hover:bg-(--primary-a5)"
              />
            }
          >
            <AgentMark size={12} />
          </TooltipTrigger>
          <TooltipContent>The agent is on this line</TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}
