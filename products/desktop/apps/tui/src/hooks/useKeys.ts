import { matchesKey } from "@earendil-works/pi-tui";
import { useApp, useInput } from "ink";
import { type Dispatch, type SetStateAction, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, canRun } from "../actions";
import { readClipboardImage } from "../clipboard";
import { type Composer, isAppKey, isTyping } from "../composer";
import { messageOf } from "../errors";
import { droppedImage } from "../images";
import {
  activeWorkspace,
  closeFocused,
  cycleFocus,
  findPane,
  focusPane,
  type LayoutState,
  newChat,
  paneIds,
  splitFocused,
} from "../layout";
import type { PiControl } from "../models";
import { moveCursor, type SheetKey, sheetKey } from "../sheet";
import { DoublePress, shortcutFor } from "../shortcuts";
import type { Notice } from "./useNotice";
import type { OpenModal } from "./useSheets";
import type { SidebarState } from "./useSidebar";

const CLOSE_CONFIRM_MS = 1_000;

type Turn = { taskId: string; runId: string } | null;

export interface Keys {
  // Raw key sequences for the focused pane; Ink's useInput handles the app's own keys.
  onKey: (sequence: string) => void;
  // Each pane reports the agent's open action offer and whether its run is mid-turn.
  setOffer: (paneId: string, offer: ActionsLine | null) => void;
  setTurn: (paneId: string, turn: Turn) => void;
  pickerFor: (paneId: string) => { index: number; dismissed: Set<string> };
}

// The keyboard: app shortcuts, sidebar keys, and typing into the focused pane's composer, sheet or offer.
export function useKeys({
  runsLocally,
  layout,
  setLayout,
  sidebar,
  composerFor,
  modalFor,
  onModalKey,
  scrollPane,
  control,
  notice: { flashNotice, clearNotice },
}: {
  runsLocally: (paneId: string, taskId: string | null) => boolean;
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  sidebar: SidebarState;
  composerFor: (paneId: string) => Composer;
  modalFor: (paneId: string) => OpenModal | undefined;
  onModalKey: (paneId: string, modal: OpenModal, key: SheetKey) => void;
  scrollPane: (paneId: string, lines: number) => void;
  control: ((taskId: string, runId: string) => PiControl) | undefined;
  notice: Notice;
}): Keys {
  const { exit } = useApp();
  const {
    rows,
    selectedIndex,
    navigating,
    setNavigating,
    activate,
    navigate,
    setCollapsed,
  } = sidebar;
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";
  // The picker's cursor and dismissals for each pane's action offer.
  const offers = useRef(new Map<string, ActionsLine | null>());
  const [pickerIndex, setPickerIndex] = useState<Map<string, number>>(
    new Map(),
  );
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const escapes = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  // Panes whose run is mid-turn, so Esc knows what to stop.
  const runningTurns = useRef(new Map<string, Turn>());

  const close = (): void => {
    if (!closeGuard.current.press(Date.now())) {
      const last =
        layout.workspaces.length === 1 && paneIds(workspace.root).length === 1;
      flashNotice(
        `Press again to ${last ? "quit" : "close this chat"}`,
        CLOSE_CONFIRM_MS,
      );
      return;
    }
    clearNotice();
    const next = closeFocused(layout);
    if (next === "quit") exit();
    else setLayout(next);
  };

  useInput((input, key) => {
    const shortcut = shortcutFor(input, key);
    if (shortcut === "close") return close();
    // Layout and chats are saved as they change, so quitting loses nothing.
    if (shortcut === "quit") return exit();
    if (shortcut === "reload") {
      // Set by cli.mjs, which owns the Vite server; absent when the app runs without it.
      (
        globalThis as { __posthogTuiReload?: () => void }
      ).__posthogTuiReload?.();
      return;
    }
    if (shortcut === "newChat") {
      setLayout(newChat);
      return;
    }
    if (shortcut) {
      const direction = shortcut === "splitDown" ? "column" : "row";
      setLayout((current) => splitFocused(current, direction));
      return;
    }
    if (key.tab) {
      setNavigating(false);
      setLayout((current) => cycleFocus(current, key.shift ? -1 : 1));
      return;
    }
    if (!sidebarFocused) {
      if (navigating && (key.upArrow || key.downArrow)) {
        navigate(key.downArrow ? 1 : -1);
      }
      if (key.pageUp) scrollPane(workspace.focusedPaneId, -10);
      if (key.pageDown) scrollPane(workspace.focusedPaneId, 10);
      return;
    }
    if (key.escape) {
      setLayout((current) => focusPane(current, workspace.focusedPaneId));
    } else if (key.downArrow || key.upArrow) {
      navigate(key.downArrow ? 1 : -1);
    } else if (key.leftArrow || key.rightArrow) {
      const row = rows[selectedIndex];
      if (row?.kind !== "workspace") return;
      setCollapsed(row.workspaceId, key.leftArrow);
    } else if (key.return) {
      setNavigating(rows[selectedIndex]?.kind === "task");
      activate(selectedIndex);
    }
  });

  const onOfferKey = (
    paneId: string,
    offer: ActionsLine,
    key: SheetKey,
  ): void => {
    const sheet = actionsSheet(offer);
    const index = pickerIndex.get(paneId) ?? 0;
    if (key.kind === "up" || key.kind === "down") {
      const next = moveCursor(sheet, index, key.kind === "up" ? -1 : 1);
      setPickerIndex((indexes) => new Map(indexes).set(paneId, next));
      return;
    }
    const action = offer.actions[Math.min(index, offer.actions.length - 1)];
    if (key.kind === "choose" && !canRun(action)) return;
    setDismissed((ids) => new Set(ids).add(offer.id));
    if (key.kind === "choose" && action.kind === "compose") {
      const next = newChat(layout);
      setLayout(next);
      composerFor(activeWorkspace(next).focusedPaneId).setText(action.prompt);
    }
  };

  // Typing in a focused pane goes to its composer; the app's own keys stay with the app.
  const onKey = (sequence: string): void => {
    if (isAppKey(sequence)) return;
    const paneId = workspace.focusedPaneId;
    // Typing from the sidebar carries on in the selected chat's composer.
    if (layout.focus === "sidebar") {
      if (!isTyping(sequence)) return;
      setNavigating(true);
      setLayout((current) => focusPane(current, paneId));
      composerFor(paneId).handleInput(sequence);
      return;
    }
    const key = sheetKey(sequence);
    const modal = modalFor(paneId);
    if (modal?.submitText && key?.kind !== "dismiss") {
      composerFor(paneId).handleInput(sequence);
      return;
    }
    if (modal) {
      if (key) onModalKey(paneId, modal, key);
      return;
    }
    if (navigating && (key?.kind === "up" || key?.kind === "down")) return;
    const composer = composerFor(paneId);
    const offer = offers.current.get(paneId);
    // With an open offer and nothing typed, arrows and Enter drive its sheet.
    if (
      offer &&
      !dismissed.has(offer.id) &&
      key &&
      key.kind !== "number" &&
      composer.isEmpty()
    ) {
      onOfferKey(paneId, offer, key);
      return;
    }
    // Esc stops a running turn; a second Esc straight after clears what is typed.
    if (key?.kind === "dismiss" && !composer.showingSuggestions()) {
      const turn = runningTurns.current.get(paneId);
      if (turn && control) {
        flashNotice("Stopping…");
        control(turn.taskId, turn.runId)
          .abort()
          .then(
            () => flashNotice("Stopped"),
            (error: unknown) =>
              flashNotice(`Couldn't stop: ${messageOf(error)}`),
          );
      }
      if (escapes.current.press(Date.now())) composer.clear();
      else if (!turn && !composer.isEmpty())
        flashNotice("Press Esc again to clear");
      return;
    }
    // Only a local agent takes images; in a cloud chat a dropped path stays text.
    const local = runsLocally(paneId, findPane(layout, paneId)?.taskId ?? null);
    if (matchesKey(sequence, "ctrl+v")) {
      if (!local) flashNotice("Images work in local chats for now");
      else
        readClipboardImage().then((image) =>
          image
            ? composer.attach(image)
            : flashNotice("There's no image on the clipboard"),
        );
      return;
    }
    const dropped = local ? droppedImage(sequence) : null;
    if (dropped) composer.attach(dropped);
    else composer.handleInput(sequence);
  };

  return {
    onKey,
    setOffer: (paneId, offer) => offers.current.set(paneId, offer),
    setTurn: (paneId, turn) => runningTurns.current.set(paneId, turn),
    pickerFor: (paneId) => ({
      index: pickerIndex.get(paneId) ?? 0,
      dismissed,
    }),
  };
}
