import { cn } from "@posthog/quill";
import type { ReactNode } from "react";

interface ComposerCardProps {
  /**
   * A plan or a set of choices to read before answering. While it is set it
   * takes the room above the input and the controls give way to it.
   */
  panel?: ReactNode;
  /** Widgets pinned above the input: a session summary, queued messages. */
  controls?: ReactNode;
  /**
   * Right-aligned chip on the row directly above the input. Holds the control
   * that opens the panel again after it is closed.
   */
  controlsEnd?: ReactNode;
  /** The prompt input itself. */
  children: ReactNode;
}

/**
 * The composer's outer card: a 2px frame that holds the panel, the controls
 * above the input and the input as one surface, so the input reads as nested
 * inside the card instead of stacked beside its chrome.
 *
 * The card sizes to its content and shrinks under whatever cap its parent
 * applies, which the session column sets at the top of the thread's scroll
 * container. The panel is the only part that gives way, so a long plan scrolls
 * from that point on rather than pushing the input out of the window.
 *
 * Each slot owns the space below itself, because an empty controls row must
 * leave the input with the same 2px the other three sides get. There is no
 * `overflow: hidden` here, since the input paints its focus ring outside its
 * border box.
 */
export function ComposerCard({
  panel,
  controls,
  controlsEnd,
  children,
}: ComposerCardProps) {
  return (
    <div className="flex min-h-0 flex-col rounded-[calc(var(--radius-sm)+2px)] border border-border bg-muted p-[2px]">
      {panel && (
        <div className="flex min-h-0 grow flex-col pb-[2px]">{panel}</div>
      )}
      <div
        className={cn(
          "grid shrink-0 transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none",
          panel ? "grid-rows-[0fr]" : "grid-rows-[1fr]",
        )}
      >
        {/* `inert` rather than unmounting, so the row can animate out and back
            in. Clipped to no height it still holds focus and takes clicks
            otherwise, which would put the tab order behind the panel. */}
        <div className="overflow-hidden" inert={!!panel}>
          {controls}
          {controlsEnd && (
            <div className="flex items-center justify-end pb-[2px]">
              {controlsEnd}
            </div>
          )}
        </div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}
