import { useEffect, useRef, useState } from "react";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import { allPanes, findPane, type LayoutState } from "../layout";
import type { LocalAgent } from "../local";
import {
  type AgentPrompt,
  promptId,
  promptReply,
  promptSheet,
  takesText,
} from "../prompts";
import { moveCursor, type Sheet, type SheetKey } from "../sheet";
import type { FlashNotice } from "./useNotice";

export interface OpenModal {
  sheet: Sheet;
  index: number;
  choose: (index: number) => void;
  // Runs on Esc, for a sheet whose opener needs to hear about a cancel.
  dismiss?: () => void;
  // Set when the answer is typed in the composer instead of picked from the list.
  submitText?: (text: string) => void;
}

export interface Sheets {
  // The sheet that takes the pane's keys, if any.
  modalFor: (paneId: string) => OpenModal | undefined;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number) => void,
  ) => void;
  onModalKey: (paneId: string, modal: OpenModal, key: SheetKey) => void;
}

// Modal sheets on the bottom of a pane: ones the app opens, and a local agent's prompts.
export function useSheets({
  layout,
  prompts,
  promptCursors,
  setPromptCursor,
  localSessions,
  composerFor,
  flashNotice,
}: {
  layout: LayoutState;
  prompts: Map<string, AgentPrompt[]>;
  promptCursors: Map<string, number>;
  setPromptCursor: (promptId: string, index: number) => void;
  localSessions: Map<string, LocalAgent>;
  composerFor: (paneId: string) => Composer;
  flashNotice: FlashNotice;
}): Sheets {
  // Modal sheets the app opened, one per pane; they take the pane's keys until closed.
  const [modals, setModals] = useState<Map<string, OpenModal>>(new Map());
  const closeModal = (paneId: string): void =>
    setModals((current) => {
      const next = new Map(current);
      next.delete(paneId);
      return next;
    });
  const paneTaskId = (paneId: string): string | null =>
    findPane(layout, paneId)?.taskId ?? null;

  // A local chat's oldest waiting prompt shows in any pane that has the chat open.
  const promptModal = (taskId: string | null): OpenModal | undefined => {
    const prompt = taskId ? prompts.get(taskId)?.[0] : undefined;
    const local = taskId ? localSessions.get(taskId) : undefined;
    if (!prompt || !local) return undefined;
    const reply = (answer: number | string | null): void => {
      local
        .answer(prompt, promptReply(prompt, answer))
        .catch((error: unknown) =>
          flashNotice(`Couldn't answer: ${messageOf(error)}`, { taskId }),
        );
    };
    return {
      sheet: promptSheet(prompt),
      index: promptCursors.get(promptId(prompt)) ?? 0,
      choose: reply,
      dismiss: () => reply(null),
      submitText: takesText(prompt) ? reply : undefined,
    };
  };

  // An editor prompt starts from the text the agent gave it.
  const prefilled = useRef(new Set<string>());
  useEffect(() => {
    for (const pane of allPanes(layout)) {
      const prompt = pane.taskId ? prompts.get(pane.taskId)?.[0] : undefined;
      if (prompt?.kind !== "dialog" || prompt.request.method !== "editor")
        continue;
      if (prefilled.current.has(prompt.request.id)) continue;
      prefilled.current.add(prompt.request.id);
      composerFor(pane.id).setText(prompt.request.prefill ?? "");
    }
  });

  return {
    modalFor: (paneId) => modals.get(paneId) ?? promptModal(paneTaskId(paneId)),
    openModal: (paneId, sheet, choose) => {
      const current = sheet.items.findIndex((item) => item.current);
      setModals((open) =>
        new Map(open).set(paneId, {
          sheet,
          index: Math.max(0, current),
          choose,
        }),
      );
    },
    onModalKey: (paneId, modal, key) => {
      if (key.kind === "up" || key.kind === "down") {
        const index = moveCursor(
          modal.sheet,
          modal.index,
          key.kind === "up" ? -1 : 1,
        );
        const prompt = modals.has(paneId)
          ? undefined
          : prompts.get(paneTaskId(paneId) ?? "")?.[0];
        if (prompt) setPromptCursor(promptId(prompt), index);
        else
          setModals((current) =>
            new Map(current).set(paneId, { ...modal, index }),
          );
        return;
      }
      if (key.kind === "dismiss") {
        closeModal(paneId);
        modal.dismiss?.();
        return;
      }
      const index = key.kind === "number" ? key.index : modal.index;
      const item = modal.sheet.items[index];
      if (!item || item.disabled) return;
      closeModal(paneId);
      modal.choose(index);
    },
  };
}
