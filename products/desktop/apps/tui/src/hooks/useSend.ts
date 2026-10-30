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
  type LayoutState,
  newChat,
  renameTask,
  renameWorkspace,
  workspaceOf,
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
  // Messages on their way, by chat (by pane before the chat has a task), shown until the chat has them.
  pending: Map<string, string>;
}

export function useSend({
  layout,
  setLayout,
  setFresh,
  setTitles,
  chats,
  taskOf,
  resetWork,
  local,
  places,
  composerFor,
  modalFor,
  openModal,
  openModelSheet,
  openEffortSheet,
  openSearch,
  onChatStarted,
  runShell,
  notice: { flashNotice, showNotice },
  login,
  logout,
}: {
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  setFresh: Dispatch<SetStateAction<Map<string, Task>>>;
  setTitles: Dispatch<SetStateAction<Map<string, string>>>;
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
  openEffortSheet: (paneId: string, task: Task | undefined) => void;
  openSearch: () => void;
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

  // A session's workspaces stay in its account's layout file, so signing out only resets what the screen holds.
  const signOut = (): void => {
    logout();
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
    if (slash?.command === "effort") {
      openEffortSheet(paneId, current);
      return;
    }
    if (slash?.command === "new") {
      setLayout(newChat);
      return;
    }
    if (slash?.command === "search") {
      openSearch();
      return;
    }
    // With no name, the command comes back with the current one to edit.
    if (slash?.command === "rename") {
      const taskId = pane?.taskId ?? null;
      const title = slash.args.trim();
      const shown = current?.title || pane?.title || "";
      if (!taskId)
        flashNotice("A new chat gets its name from its first message");
      else if (!title) composerFor(paneId).setText(`/rename ${shown}`);
      else if (!chats) flashNotice("Sign in to rename a chat: type /login");
      else {
        // Shown at once; a failed rename puts the old name back, unless a later rename has replaced it.
        setTitles((titles) => new Map(titles).set(taskId, title));
        chats.rename(taskId, title).then(
          (task) => {
            setFresh((tasks) => new Map(tasks).set(task.id, task));
            setLayout((state) => renameTask(state, taskId, taskId, title));
            flashNotice(`Renamed to ${title}`);
          },
          (error: unknown) => {
            setTitles((titles) => {
              if (titles.get(taskId) !== title) return titles;
              const next = new Map(titles);
              next.delete(taskId);
              return next;
            });
            flashNotice(`Couldn't rename this chat: ${messageOf(error)}`);
          },
        );
      }
      return;
    }
    if (slash?.command === "rename-workspace") {
      const workspace = workspaceOf(layout, paneId);
      const name = slash.args.trim();
      if (!workspace || workspace.root.kind === "pane")
        flashNotice(
          "This chat isn't in a workspace. Split it with Ctrl+S first",
        );
      else if (!name)
        composerFor(paneId).setText(
          `/rename-workspace ${workspace.name ?? ""}`.trimEnd(),
        );
      else {
        setLayout((state) => renameWorkspace(state, workspace.id, name));
        flashNotice(`Renamed the workspace to ${name}`);
      }
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
    let pendingKey = pane?.taskId ?? paneId;
    setPending((messages) => new Map(messages).set(pendingKey, text));
    const clearPending = (): void =>
      setPending((messages) => {
        const next = new Map(messages);
        next.delete(pendingKey);
        return next;
      });
    // A new chat's message moves to its task, so it stays with the chat when the pane shows another.
    const pendingFor = (taskId: string): void => {
      clearPending();
      pendingKey = taskId;
      setPending((messages) => new Map(messages).set(taskId, text));
    };
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
          pendingFor(task.id);
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
    (current
      ? chats.reply(current, text, images)
      : chats.start(text, images)
    ).then(
      (task) => {
        setFresh((tasks) => new Map(tasks).set(task.id, task));
        if (!current) {
          onChatStarted(paneId, task.id);
          pendingFor(task.id);
          const title = task.title || text.slice(0, 80);
          setLayout((state) => assignTask(state, paneId, task.id, title));
        }
      },
      (error: unknown) => {
        clearPending();
        composerFor(paneId).putBack(text, images);
        flashNotice(
          `Couldn't send: ${messageOf(error)}. Your message is still in the composer.`,
        );
      },
    );
  };

  return { onSubmit, pending };
}
