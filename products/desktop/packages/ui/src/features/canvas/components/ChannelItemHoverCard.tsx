import { PreviewCard } from "@base-ui/react/preview-card";
import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { Card } from "@posthog/quill";
import {
  ChannelItemPreview,
  type ChannelItemPreviewPayload,
} from "@posthog/ui/features/canvas/components/ChannelItemPreview";
import {
  SpacePreview,
  type SpacePreviewPayload,
} from "@posthog/ui/features/canvas/components/SpacePreview";
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { useIsPinDragging } from "@posthog/ui/features/sidebar/pinDragStore";
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

/**
 * What the sidebar's one card can be showing. A space and a session are
 * different cards, but they are the same popup being moved between rows: the
 * pointer crosses from a space to a session inside it without either card
 * re-waiting its open delay, which is the whole reason the handle is shared.
 */
export type ChannelPreviewPayload =
  | ({ kind: "item" } & ChannelItemPreviewPayload)
  | ({ kind: "space" } & SpacePreviewPayload);

/**
 * The shared card, and who currently owns it.
 *
 * Ownership matters because the card is one popup and two things move it. A
 * keyboard-opened card belongs to the row the highlight is on, and that row
 * takes it away again when the highlight leaves — but only while it still owns
 * it. Without that, arrowing on after the pointer had moved the card elsewhere
 * closed the card out from under the pointer.
 */
interface ChannelPreviewCard {
  handle: PreviewCard.Handle<ChannelPreviewPayload>;
  /** Open on a row the keyboard has settled on, and claim the card for it. */
  openFromKeyboard: (triggerId: string) => void;
  /** Close, but only if the keyboard's card is still this row's. */
  closeFromKeyboard: (triggerId: string) => void;
  /** The pointer is driving now; the keyboard no longer owns what it opened. */
  releaseKeyboard: () => void;
}

const ChannelItemPreviewHandleContext =
  createContext<ChannelPreviewCard | null>(null);

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
    PreviewCard.createHandle<ChannelPreviewPayload>(),
  );
  const [open, setOpen] = useState(false);
  const [submenuOpen, setSubmenuOpen] = useState(false);
  const close = useCallback(() => {
    setSubmenuOpen(false);
    handle.close();
  }, [handle]);

  // A drag passes the pointer over row after row, each handing the card to the
  // next, until a card this size sits over the list. It stands down instead.
  const dragging = useIsPinDragging();
  useEffect(() => {
    if (dragging) close();
  }, [dragging, close]);

  // Which row's keypress the open card belongs to, if any.
  const keyboardTrigger = useRef<string | null>(null);
  const card = useMemo<ChannelPreviewCard>(
    () => ({
      handle,
      openFromKeyboard: (triggerId) => {
        keyboardTrigger.current = triggerId;
        handle.open(triggerId);
      },
      closeFromKeyboard: (triggerId) => {
        if (keyboardTrigger.current !== triggerId) return;
        keyboardTrigger.current = null;
        handle.close();
      },
      releaseKeyboard: () => {
        keyboardTrigger.current = null;
      },
    }),
    [handle],
  );

  return (
    <ChannelItemPreviewHandleContext.Provider value={card}>
      {children}
      {/* Controlled so the card survives its own submenu: "File to…" opens in a
          portal outside the card, and the pointer moving there reads as leaving
          the card, which would take the menu down with it. */}
      <PreviewCard.Root
        handle={handle}
        open={(open || submenuOpen) && !dragging}
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
                  {payload.kind === "space" ? (
                    <SpacePreview payload={payload} onAction={close} />
                  ) : (
                    <ChannelItemPreview
                      // Keyed on the row, so crossing to another one unmounts
                      // the card rather than reusing it — which is what lowers
                      // the submenu flag. Base UI reports no close on unmount,
                      // and a flag left raised pins `open || submenuOpen` true
                      // on a card nothing can then dismiss.
                      key={payload.item.key}
                      payload={payload}
                      onAction={close}
                      onSubmenuOpenChange={setSubmenuOpen}
                    />
                  )}
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
 *
 * "Takes it away" only where the keyboard's card is still this row's. The
 * pointer moves the same popup between rows without telling the row that opened
 * it, so a highlight leaving after that would otherwise close a card the
 * pointer is sitting on.
 */
function useKeyboardPreview(
  card: ChannelPreviewCard | null,
  triggerId: string,
  highlighted: boolean,
): void {
  useEffect(() => {
    if (!card || !highlighted) return;
    const timer = setTimeout(
      () => card.openFromKeyboard(triggerId),
      KEYBOARD_OPEN_DELAY_MS,
    );
    return () => {
      clearTimeout(timer);
      card.closeFromKeyboard(triggerId);
    };
  }, [card, highlighted, triggerId]);
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
  const card = useContext(ChannelItemPreviewHandleContext);
  // The card reads the row it is over off the active trigger, so what the row
  // has to say travels as the trigger's payload. Kept stable, because a new
  // identity writes it to the card's store again.
  const payload = useMemo(
    () => ({ kind: "item" as const, item, menu }),
    [item, menu],
  );
  // Ours rather than Base UI's own, because opening from the keyboard means
  // naming the trigger to open.
  const triggerId = useId();
  useKeyboardPreview(card, triggerId, highlighted);
  const row = (
    // Pointing at any row hands the card to the pointer, so the row the
    // keyboard opened it on stops trying to close it.
    <div className="flex min-w-0" onPointerEnter={card?.releaseKeyboard}>
      {children}
    </div>
  );

  // No provider, no card. A row still has its right-click menu, and every fact
  // the card names is on the row itself.
  if (!card) return row;

  return (
    <PreviewCard.Trigger
      handle={card.handle}
      payload={payload}
      id={triggerId}
      delay={OPEN_DELAY_MS}
      closeDelay={CLOSE_DELAY_MS}
      render={row}
    />
  );
}

/**
 * A space row that shows the shared preview card while it is pointed at, with
 * the space's own card in it rather than a session's.
 *
 * The same handle as the session rows on purpose: a space and the sessions
 * under it are one list to the pointer, so crossing between them swaps the
 * card's contents instead of closing one popup and opening another. It opens on
 * the keyboard's highlight the way they do, too — walking the tree shows the
 * same card whichever kind of row the highlight lands on.
 */
export function SpaceHoverCard({
  space,
  highlighted = false,
  children,
}: {
  space: SpacePreviewPayload;
  /** The keyboard is on this row, which opens the card as hovering does. */
  highlighted?: boolean;
  children: ReactNode;
}) {
  const card = useContext(ChannelItemPreviewHandleContext);
  // Stable for the reason a session row's is: a new identity writes the payload
  // to the card's store again. The caller memoizes what it passes.
  const payload = useMemo(
    () => ({ kind: "space" as const, ...space }),
    [space],
  );
  const triggerId = useId();
  useKeyboardPreview(card, triggerId, highlighted);
  const row = (
    <div className="flex min-w-0" onPointerEnter={card?.releaseKeyboard}>
      {children}
    </div>
  );

  if (!card) return row;

  return (
    <PreviewCard.Trigger
      handle={card.handle}
      payload={payload}
      id={triggerId}
      delay={OPEN_DELAY_MS}
      closeDelay={CLOSE_DELAY_MS}
      render={row}
    />
  );
}
