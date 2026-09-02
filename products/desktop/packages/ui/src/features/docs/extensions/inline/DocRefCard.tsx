import { Popover } from "@base-ui/react/popover";
import { cn } from "@posthog/quill";
import type { ReactElement, ReactNode } from "react";
import { useState } from "react";
import type { InlineRefCard } from "./types";

const OPEN_DELAY_MS = 200;
const CLOSE_DELAY_MS = 100;

/**
 * The one card every hovered thing in a doc opens.
 *
 * Self-styled rather than quill's popover, which is not loaded on every
 * surface a doc renders on, and matched to the evidence card so the two read
 * as one thing.
 */
export function DocRefHover({
  card,
  trigger,
  nativeButton = false,
  side = "top",
}: {
  card?: InlineRefCard;
  trigger: ReactElement;
  /** The trigger is a real button, so Base UI must not synthesize one. */
  nativeButton?: boolean;
  side?: "top" | "left";
}): ReactElement {
  const [open, setOpen] = useState(false);
  if (!card) return trigger;
  const close = () => setOpen(false);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        openOnHover
        delay={OPEN_DELAY_MS}
        closeDelay={CLOSE_DELAY_MS}
        nativeButton={nativeButton}
        onFocus={() => setOpen(true)}
        render={trigger}
      />
      {open && (
        <Popover.Portal>
          <Popover.Positioner side={side} sideOffset={8} className="z-[9999]">
            <Popover.Popup
              data-testid="doc-ref-card"
              className={cn(
                "rounded-[6px] border border-(--gray-4) bg-(--gray-2) text-(--gray-12) outline-none",
                card.render ? "" : "w-64 p-2.5",
              )}
              style={{ boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)" }}
            >
              {card.render ? (
                card.render(close)
              ) : (
                <DefaultCardBody card={card} onDone={close} />
              )}
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      )}
    </Popover.Root>
  );
}

/** The row of actions at the foot of a card. A label never splits mid-word:
 * when the row runs out of width, a whole action drops to the next line
 * instead. */
export function DocRefCardActions({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  return (
    <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {children}
    </div>
  );
}

export function DocRefCardAction({
  children,
  onSelect,
}: {
  children: ReactNode;
  onSelect: () => void;
}): ReactElement {
  return (
    <button
      type="button"
      className="flex-none cursor-pointer whitespace-nowrap border-none bg-transparent p-0 text-(--gray-11) text-[11px] hover:text-(--gray-12)"
      onClick={onSelect}
    >
      {children}
    </button>
  );
}

function DefaultCardBody({
  card,
  onDone,
}: {
  card: InlineRefCard;
  onDone: () => void;
}): ReactElement {
  return (
    <>
      <span className="line-clamp-2 block font-semibold text-[13px] leading-snug">
        {card.title}
      </span>
      {card.meta ? (
        <span className="mt-1.5 flex items-center gap-1 text-(--gray-10) text-[10.5px]">
          {card.meta}
        </span>
      ) : null}
      {card.action ? (
        <DocRefCardActions>
          <DocRefCardAction
            onSelect={() => {
              card.action?.onSelect();
              onDone();
            }}
          >
            {card.action.label}
          </DocRefCardAction>
        </DocRefCardActions>
      ) : null}
    </>
  );
}
