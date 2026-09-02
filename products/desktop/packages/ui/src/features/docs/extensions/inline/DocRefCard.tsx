import { Popover } from "@base-ui/react/popover";
import { cn } from "@posthog/quill";
import type { ReactElement } from "react";
import { useState } from "react";
import type { InlineRefCard } from "./types";

const OPEN_DELAY_MS = 200;
const CLOSE_DELAY_MS = 100;

/**
 * The one card every inline reference opens on hover.
 *
 * Self-styled rather than quill's popover, which is not loaded on every
 * surface a doc renders on, and matched to the evidence card so the two read
 * as one thing.
 */
export function DocRefHover({
  card,
  trigger,
  nativeButton = false,
}: {
  card?: InlineRefCard;
  trigger: ReactElement;
  /** The trigger is a real button, so Base UI must not synthesize one. */
  nativeButton?: boolean;
}): ReactElement {
  const [open, setOpen] = useState(false);
  if (!card) return trigger;

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
          <Popover.Positioner side="top" sideOffset={8} className="z-[9999]">
            <Popover.Popup
              data-testid="doc-ref-card"
              className={cn(
                "rounded-[6px] border border-(--gray-4) bg-(--gray-2) text-(--gray-12) outline-none",
                card.render ? "" : "w-64 p-2.5",
              )}
              style={{ boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)" }}
            >
              {card.render ? (
                card.render()
              ) : (
                <DefaultCardBody card={card} onDone={() => setOpen(false)} />
              )}
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      )}
    </Popover.Root>
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
        <button
          type="button"
          className="mt-2.5 cursor-pointer border-none bg-transparent p-0 text-(--gray-11) text-[11px] hover:text-(--gray-12)"
          onClick={() => {
            card.action?.onSelect();
            onDone();
          }}
        >
          {card.action.label}
        </button>
      ) : null}
    </>
  );
}
