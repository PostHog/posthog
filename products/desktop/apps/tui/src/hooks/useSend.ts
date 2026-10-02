import type { ImageContent } from "@earendil-works/pi-ai";
import type { CloudRegion, Task } from "@posthog/shared";
import { type Dispatch, type SetStateAction, useState } from "react";
import { REGIONS } from "../auth";
import type { PiChats } from "../chats";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import {
  assignTask,
  findPane,
  initialLayout,
  type LayoutState,
  newChat,
  saveLayout,
} from "../layout";
import type { LocalSession } from "../local";
import { parseSlash } from "../models";
import type { ChatPlace } from "../prefs";
import type { Sheet } from "../sheet";
import { parseShell } from "../shell";
import type { Notice } from "./useNotice";
import type { OpenModal } from "./useSheets";

export interface Send {
  // What the composer submits: an answer to a typed prompt, a slash command, a ! command, or a message.
  onSubmit: (paneId: string, text: string, images?: ImageContent[]) => void;
  // Messages on their way, by pane, shown until the chat has them.
  pending: Map<string, string>;
}

export function useSend({
  layout,
  setLayout,
  setFresh,
  chats,
  taskOf,
  resetWork,
  local,
  places,
  composerFor,
  modalFor,
  openModal,
  openModelSheet,
  onChatStarted,
  runShell,
  notice: { flashNotice, showNotice },
  login,
  logout,
}: {
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  setFresh: Dispatch<SetStateAction<Map<string, Task>>>;
  chats: PiChats | undefined;
  taskOf: (taskId: string | null) => Task | undefined;
  resetWork: () => void;
  local: {
    isLocal: (taskId: string | null) => taskId is string;
    localFor: (id: string) => Promise<LocalSession>;
    clear: (id: string) => Promise<void>;
    markActive: (taskId: string) => void;
  };
  places: {
    placeFor: (paneId: string) => ChatPlace;
    setPlace: (paneId: string, place: ChatPlace) => void;
  };
  composerFor: (paneId: string) => Composer;
  modalFor: (paneId: string) => OpenModal | undefined;
  openModal: (
    paneId: string,
    sheet: Sheet,
    choose: (index: number) => void,
  ) => void;
  openModelSheet: (paneId: string, task: Task | undefined) => void;
  onChatStarted: (paneId: string, taskId: string) => void;
  runShell: (
    paneId: string,
    taskId: string | null,
    command: string,
    text: string,
  ) => void;
  notice: Notice;
  login: (region: CloudRegion, onAuth: (url: string) => void) => Promise<void>;
  logout: () => void;
}): Send {
  const { isLocal, localFor, markActive } = local;
  const [pending, setPending] = useState<Map<string, string>>(new Map());

  const openLoginSheet = (paneId: string, description: string): void => {
    openModal(
      paneId,
      {
        title: "Sign in to PostHog",
        description,
        items: REGIONS.map((region) => ({ label: region.label })),
        footer: "Enter to open your browser · Esc to cancel",
      },
      (index) => {
        const region = REGIONS[index];
        showNotice("Finish signing in with your browser…");
        login(region.id, () => {}).then(
          () => flashNotice(`Signed in to ${region.label}`),
          (error: unknown) =>
            flashNotice(`Sign-in failed: ${messageOf(error)}`),
        );
      },
    );
  };

  // A session's workspaces belong to its account, so signing out starts from one empty chat.
  const signOut = (): void => {
    logout();
    const fresh = initialLayout();
    setLayout(fresh);
    saveLayout(fresh);
    resetWork();
    setFresh(new Map());
    setPending(new Map());
    flashNotice("Signed out");
  };

  const onSubmit = (
    paneId: string,
    text: string,
    images: ImageContent[] = [],
  ): void => {
    const pane = findPane(layout, paneId);
    const current = taskOf(pane?.taskId ?? null);
    const textPrompt = modalFor(paneId)?.submitText;
    if (textPrompt) {
      textPrompt(text);
      return;
    }
    const slash = parseSlash(text);
    if (slash?.command === "model") {
      openModelSheet(paneId, current);
      return;
    }
    if (slash?.command === "new") {
      setLayout(newChat);
      return;
    }
    if (slash?.command === "clear") {
      const taskId = pane?.taskId ?? null;
      if (!taskId) flashNotice("There's nothing to clear yet");
      else if (!isLocal(taskId))
        flashNotice(
          "You can't clear a cloud run. Type /new to start a new chat",
        );
      else
        local.clear(taskId).then(
          () => flashNotice("Cleared this chat"),
          (error: unknown) =>
            flashNotice(`Couldn't clear this chat: ${messageOf(error)}`),
        );
      return;
    }
    if (slash?.command === "local" || slash?.command === "cloud") {
      const mode = slash.command;
      places.setPlace(paneId, mode);
      flashNotice(
        mode === "local"
          ? `New chats run on this machine, in ${process.cwd()}`
          : "New chats run in the cloud",
      );
      return;
    }
    if (slash?.command === "login") {
      openLoginSheet(paneId, "Pick the PostHog you sign in to.");
      return;
    }
    if (slash?.command === "logout") {
      signOut();
      return;
    }
    const shell = parseShell(text);
    if (shell) {
      runShell(paneId, pane?.taskId ?? null, shell, text);
      return;
    }
    // Signed out, a message waits in the composer while the user signs in.
    if (!chats) {
      composerFor(paneId).setText(text);
      openLoginSheet(
        paneId,
        "Sign in to send this message. It stays in the composer.",
      );
      return;
    }
    setPending((messages) => new Map(messages).set(paneId, text));
    const clearPending = (): void =>
      setPending((messages) => {
        const next = new Map(messages);
        next.delete(paneId);
        return next;
      });
    const promptLocal = (taskId: string): Promise<void> => {
      markActive(taskId);
      return localFor(taskId).then((session) => session.prompt(text, images));
    };
    if (isLocal(pane?.taskId ?? null)) {
      promptLocal(pane?.taskId as string).catch((error: unknown) => {
        clearPending();
        flashNotice(`Couldn't send: ${messageOf(error)}`);
      });
      return;
    }
    // A local chat starts with its task row, so it is never only on this machine; without one, the message stays in the composer.
    if (!pane?.taskId && places.placeFor(paneId) === "local") {
      chats.createLocal(text).then(
        (task) => {
          setFresh((tasks) => new Map(tasks).set(task.id, task));
          onChatStarted(paneId, task.id);
          setLayout((state) =>
            assignTask(state, paneId, task.id, task.title || text.slice(0, 80)),
          );
          promptLocal(task.id).catch((error: unknown) => {
            clearPending();
            flashNotice(`Couldn't send: ${messageOf(error)}`);
          });
        },
        (error: unknown) => {
          clearPending();
          composerFor(paneId).setText(text);
          flashNotice(
            `Couldn't start the chat: ${messageOf(error)}. Your message is still in the composer.`,
          );
        },
      );
      return;
    }
    (current ? chats.reply(current, text) : chats.start(text)).then(
      (task) => {
        setFresh((tasks) => new Map(tasks).set(task.id, task));
        if (!current) {
          onChatStarted(paneId, task.id);
          const title = task.title || text.slice(0, 80);
          setLayout((state) => assignTask(state, paneId, task.id, title));
        }
      },
      (error: unknown) => {
        clearPending();
        flashNotice(`Couldn't send: ${messageOf(error)}`);
      },
    );
  };

  return { onSubmit, pending };
}
