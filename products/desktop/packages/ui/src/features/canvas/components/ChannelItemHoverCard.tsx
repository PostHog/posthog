import { PreviewCard } from "@base-ui/react/preview-card";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { Card } from "@posthog/quill";
import {
  ChannelItemPreview,
  type ChannelItemPreviewPayload,
} from "@posthog/ui/features/canvas/components/ChannelItemPreview";
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

/**
 * How long the pointer has to rest on a row before its card opens — the first
 * time. Once a card is open, moving to another row swaps it with no delay at
 * all (Base UI treats triggers that share a handle as one popup being moved),
 * which is the whole reason the list shares one card.
 */
const OPEN_DELAY_MS = 400;
const CLOSE_DELAY_MS = 100;

/**
 * How long the keyboard has to rest on a row before its card opens. Long enough
 * that arrowing through the list doesn't flash a card on every row it passes.
 */
const KEYBOARD_OPEN_DELAY_MS = 350;

const ChannelItemPreviewHandleContext =
  createContext<PreviewCard.Handle<ChannelItemPreviewPayload> | null>(null);

/**
 * One hover card for every session row in the sidebar, rather than one per row.
 *
 * Rows are cheap and there are hundreds of them across an expanded tree; a
 * preview card each meant hundreds of popup roots, each with its own floating
 * context and open state, built while the list rendered and thrown away when it
 * scrolled. Here the rows are only triggers on a shared handle, and the card —
 * with the queries and derivations behind its contents — is built once, for
 * whichever row is being pointed at.
 *
 * Sharing the handle is also what makes sliding down the list feel like one
 * card moving: Base UI skips the open delay when the pointer crosses to another
 * trigger of an already-open popup.
 */
export function ChannelItemPreviewCardProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [handle] = useState(() =>
    PreviewCard.createHandle<ChannelItemPreviewPayload>(),
  );
  const [open, setOpen] = useState(false);
  const [submenuOpen, setSubmenuOpen] = useState(false);
  const close = useCallback(() => {
    setSubmenuOpen(false);
    handle.close();
  }, [handle]);

  return (
    <ChannelItemPreviewHandleContext.Provider value={handle}>
      {children}
      {/* Controlled so the card survives its own submenu: "File to…" opens in a
          portal outside the card, and the pointer moving there reads as leaving
          the card, which would take the menu down with it. */}
      <PreviewCard.Root
        handle={handle}
        open={open || submenuOpen}
        onOpenChange={setOpen}
      >
        {({ payload }) =>
          payload ? (
            <PreviewCard.Portal>
              <PreviewCard.Positioner
                side="right"
                align="start"
                sideOffset={10}
                className="z-50"
              >
                {/* The card is quill's `Card` and `Item` parts throughout — the
                    popup itself carries no surface styling, so this window's
                    hover card matches every other card in the app rather than a
                    hand-tuned shadow of its own. The card's own padding is off
                    (`gap-0 py-0`): each section pays for its own inset, which is
                    what lets the rules run edge to edge and the action rows
                    highlight full width. */}
                <PreviewCard.Popup
                  render={
                    <Card
                      size="sm"
                      className="w-72 gap-0 border border-border py-0 shadow-md"
                    />
                  }
                >
                  <ChannelItemPreview
                    payload={payload}
                    onAction={close}
                    onSubmenuOpenChange={setSubmenuOpen}
                  />
                </PreviewCard.Popup>
              </PreviewCard.Positioner>
            </PreviewCard.Portal>
          ) : null
        }
      </PreviewCard.Root>
    </ChannelItemPreviewHandleContext.Provider>
  );
}

/**
 * Opens the shared card on a row the keyboard has settled on, and takes it away
 * again the moment the highlight moves — a card still open once the highlight
 * has gone points at the wrong row.
 */
function useKeyboardPreview(
  handle: PreviewCard.Handle<ChannelItemPreviewPayload> | null,
  triggerId: string,
  highlighted: boolean,
): void {
  const openedByKeyboard = useRef(false);

  useEffect(() => {
    if (!handle || !highlighted) return;
    const timer = setTimeout(() => {
      handle.open(triggerId);
      openedByKeyboard.current = true;
    }, KEYBOARD_OPEN_DELAY_MS);
    return () => {
      clearTimeout(timer);
      if (!openedByKeyboard.current) return;
      openedByKeyboard.current = false;
      handle.close();
    };
  }, [handle, highlighted, triggerId]);
}

/**
 * A row that shows the shared preview card while it is pointed at. Shared by
 * the channel sidebar's rows and the space tree's session rows so the two can't
 * drift into showing different facts or actions for one task.
 *
 * `children` is the row itself, handed to the trigger.
 */
export function ChannelItemHoverCard({
  item,
  menu,
  highlighted = false,
  children,
}: {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
  /** The keyboard is on this row, which opens the card as hovering does. */
  highlighted?: boolean;
  children: ReactNode;
}) {
  const handle = useContext(ChannelItemPreviewHandleContext);
  // The card reads the row it is over off the active trigger, so what the row
  // has to say travels as the trigger's payload. Kept stable, because a new
  // identity writes it to the card's store again.
  const payload = useMemo(() => ({ item, menu }), [item, menu]);
  // Ours rather than Base UI's own, because opening from the keyboard means
  // naming the trigger to open.
  const triggerId = useId();
  useKeyboardPreview(handle, triggerId, highlighted);
  const row = <div className="flex min-w-0">{children}</div>;

  // No provider, no card. A row still has its right-click menu, and every fact
  // the card names is on the row itself.
  if (!handle) return row;

  return (
    <PreviewCard.Trigger
      handle={handle}
      payload={payload}
      id={triggerId}
      delay={OPEN_DELAY_MS}
      closeDelay={CLOSE_DELAY_MS}
      render={row}
    />
  );
}
