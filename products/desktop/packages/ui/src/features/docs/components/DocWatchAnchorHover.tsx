import { Popover } from "@base-ui/react/popover";
import type { DocSchemas } from "@posthog/api-client/docs";
import type { Editor } from "@tiptap/core";
import { useEffect, useState } from "react";
import {
  DocRefCardAction,
  DocRefCardActions,
} from "../extensions/inline/DocRefCard";
import { statusLine, VerdictPill } from "./DocWatchCard";

const WATCH_ANCHOR = '.doc-discussion-anchor[data-kind="watch"]';
const OPEN_DELAY_MS = 200;
const CLOSE_DELAY_MS = 120;

interface Hovered {
  anchorKey: string;
  element: HTMLElement;
}

/** The card that opens when the pointer rests on a watched phrase in the page. */
export function DocWatchAnchorHover({
  editor,
  threads,
  onOpen,
}: {
  editor: Editor | null;
  threads: DocSchemas.DiscussionThread[];
  onOpen: (anchorKey: string) => void;
}) {
  const [hovered, setHovered] = useState<Hovered | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const dom = editor?.view.dom;
    if (!dom) return;
    let openTimer: ReturnType<typeof setTimeout> | undefined;
    let closeTimer: ReturnType<typeof setTimeout> | undefined;

    const onOver = (event: MouseEvent) => {
      const element = (
        event.target as HTMLElement | null
      )?.closest<HTMLElement>(WATCH_ANCHOR);
      if (!element) return;
      clearTimeout(closeTimer);
      const anchorKey = element.dataset.anchorKey ?? "";
      openTimer = setTimeout(() => {
        setHovered({ anchorKey, element });
        setOpen(true);
      }, OPEN_DELAY_MS);
    };
    const onOut = (event: MouseEvent) => {
      const element = (event.target as HTMLElement | null)?.closest(
        WATCH_ANCHOR,
      );
      if (!element) return;
      clearTimeout(openTimer);
      closeTimer = setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
    };

    dom.addEventListener("mouseover", onOver);
    dom.addEventListener("mouseout", onOut);
    return () => {
      clearTimeout(openTimer);
      clearTimeout(closeTimer);
      dom.removeEventListener("mouseover", onOver);
      dom.removeEventListener("mouseout", onOut);
    };
  }, [editor]);

  const thread = threads.find(
    (candidate) => candidate.anchor_key === hovered?.anchorKey,
  );
  const watch = thread?.watch;
  if (!hovered || !watch) return null;

  const close = () => setOpen(false);
  const summary = watch.verdict.reason || statusLine(watch);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Portal>
        <Popover.Positioner
          anchor={hovered.element}
          side="top"
          sideOffset={8}
          className="z-[9999]"
        >
          <Popover.Popup
            data-testid="doc-ref-card"
            className="w-64 rounded-[6px] border border-(--gray-4) bg-(--gray-2) p-2.5 text-(--gray-12) outline-none"
            style={{ boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)" }}
          >
            <div className="flex items-start gap-2">
              <VerdictPill watch={watch} />
              <span className="line-clamp-2 min-w-0 flex-1 whitespace-normal text-(--gray-11) text-[11.5px] leading-snug">
                {summary}
              </span>
            </div>
            <DocRefCardActions>
              <DocRefCardAction
                onSelect={() => {
                  onOpen(hovered.anchorKey);
                  close();
                }}
              >
                Open the watch
              </DocRefCardAction>
            </DocRefCardActions>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
