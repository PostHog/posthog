import { useEffect, useRef, useState } from "react";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import { allPanes, findPane, type LayoutState } from "../layout";
import {
  type AgentPrompt,
  type PromptReply,
  promptId,
  promptReply,
  promptSheet,
  questionsOf,
  takesText,
  wantsText,
} from "../prompts";
import { editQuery } from "../search";
import { moveCursor, type Sheet, type SheetKey } from "../sheet";
import type { FlashNotice } from "./useNotice";

export interface OpenModal {
  sheet: Sheet;
  index: number;
  // The chosen item, with its text field's contents when it has one.
  choose: (index: number, text?: string) => void;
  // Runs on Esc, for a sheet whose opener needs to hear about a cancel.
  dismiss?: () => void;
  // Takes a key typed into the selected item's text field.
  // Keys arrive in bursts before React renders, so it applies the key to the text as last edited, never as last drawn.
  edit?: (sequence: string) => void;
  // Set when the answer is typed in the composer instead of picked from the list.
  submitText?: (text: string) => void;
}

export interface Sheets {
  // The sheet that takes the pane's keys, if any.
  modalFor: (paneId: string) => OpenModal | undefined;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number, text?: string) => void,
    dismiss?: () => void,
  ) => void;
  closeModal: (paneId: string) => void;
  onModalKey: (paneId: string, modal: OpenModal, key: SheetKey) => void;
}

// Modal sheets on the bottom of a pane: ones the app opens, and a local agent's prompts.
export function useSheets({
  layout,
  prompts,
  promptCursors,
  setPromptCursor,
  answer,
  composerFor,
  flashNotice,
}: {
  layout: LayoutState;
  prompts: Map<string, AgentPrompt[]>;
  promptCursors: Map<string, number>;
  setPromptCursor: (promptId: string, index: number) => void;
  // Sends a chat's answer to the agent that asked, on this machine or in the cloud.
  answer: (
    taskId: string,
    prompt: AgentPrompt,
    reply: PromptReply,
  ) => Promise<void>;
  composerFor: (paneId: string) => Composer;
  flashNotice: FlashNotice;
}): Sheets {
  // Modal sheets the app opened, one per pane; they take the pane's keys until closed.
  const [modals, setModals] = useState<Map<string, OpenModal>>(new Map());
  // What is typed into an app-opened sheet's text field, by pane: a ref, as the prompts' drafts below.
  const typed = useRef(new Map<string, string>()).current;
  const closeModal = (paneId: string): void => {
    typed.delete(paneId);
    setModals((current) => {
      const next = new Map(current);
      next.delete(paneId);
      return next;
    });
  };
  const withTyped = (paneId: string, modal: OpenModal): OpenModal => {
    const text = typed.get(paneId);
    if (text === undefined) return modal;
    const items = modal.sheet.items.map((item) =>
      item.input ? { ...item, input: { ...item.input, text } } : item,
    );
    return { ...modal, sheet: { ...modal.sheet, items } };
  };
  const paneTaskId = (paneId: string): string | null =>
    findPane(layout, paneId)?.taskId ?? null;
  // A question prompt's picks so far, and the text typed for an option that takes some, by prompt.
  // Keys arrive in bursts before React renders, so each one reads what the last one left: refs, with a render asked for.
  const answered = useRef(new Map<string, Record<string, string>>()).current;
  const drafts = useRef(new Map<string, string>()).current;
  const [, setChanged] = useState(0);
  const changed = (): void => setChanged((count) => count + 1);
  const forget = (id: string): void => {
    answered.delete(id);
    drafts.delete(id);
    changed();
  };

  // A chat's oldest waiting prompt shows in any pane that has the chat open.
  const promptModal = (taskId: string | null): OpenModal | undefined => {
    const prompt = taskId ? prompts.get(taskId)?.[0] : undefined;
    if (!prompt || !taskId) return undefined;
    const id = promptId(prompt);
    const picks = answered.get(id) ?? {};
    const draft = drafts.get(id) ?? "";
    const send = (next: PromptReply): void => {
      forget(id);
      answer(taskId, prompt, next).catch((error: unknown) =>
        flashNotice(`Couldn't answer: ${messageOf(error)}`, { taskId }),
      );
    };
    const reply = (answer: number | string | null): void => {
      const typed =
        typeof answer === "number" && wantsText(prompt, answer)
          ? draft.trim() || undefined
          : undefined;
      const next = promptReply(prompt, answer, picks, typed);
      const answers = next.kind === "acp" ? (next.answers ?? {}) : {};
      const count = Object.keys(answers).length;
      if (answer !== null && count > 0 && count < questionsOf(prompt).length) {
        answered.set(id, answers);
        setPromptCursor(id, 0);
        changed();
        return;
      }
      send(next);
    };
    return {
      sheet: promptSheet(prompt, Object.keys(picks).length, draft),
      index: promptCursors.get(id) ?? 0,
      choose: reply,
      dismiss: () => reply(null),
      edit: (sequence) => {
        drafts.set(id, editQuery(draft, sequence));
        changed();
      },
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
    modalFor: (paneId) => {
      const modal = modals.get(paneId);
      return modal ? withTyped(paneId, modal) : promptModal(paneTaskId(paneId));
    },
    closeModal,
    openModal: (paneId, sheet, choose, dismiss) => {
      // The cursor starts on the item the setting holds, else the first one that can be chosen.
      const held = sheet.items.findIndex((item) => item.current);
      const current =
        held >= 0 ? held : sheet.items.findIndex((item) => !item.disabled);
      const field = sheet.items.find((item) => item.input)?.input;
      typed.delete(paneId);
      setModals((open) =>
        new Map(open).set(paneId, {
          sheet,
          index: Math.max(0, current),
          choose,
          dismiss,
          edit: (sequence) => {
            typed.set(
              paneId,
              editQuery(typed.get(paneId) ?? field?.text ?? "", sequence),
            );
            changed();
          },
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
      // A number lands the cursor on an item with a text field, so typing can start; Enter sends it.
      if (key.kind === "number" && item.input) {
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
      closeModal(paneId);
      modal.choose(index, item.input?.text);
    },
  };
}
