import type { ImageContent } from "@earendil-works/pi-ai";
import type { CloudRegion, Task } from "@posthog/shared";
import { type Dispatch, type SetStateAction, useRef, useState } from "react";
import { REGIONS } from "../auth";
import {
  BILLINGS,
  billingBlocker,
  billingNotice,
  billingSheet,
  cloudHarnessFor,
  localHarnessFor,
} from "../billing";
import { chatgptAccount } from "../chatgpt";
import type { PiChats, StartPick } from "../chats";
import { loadClaudeToken } from "../claudeToken";
import type { Composer } from "../composer";
import { messageOf } from "../errors";
import {
  assignTask,
  expandPane,
  findPane,
  type LayoutState,
  newChatIn,
  optimizeWorkspace,
  renameTask,
  renameWorkspace,
  workspaceOf,
} from "../layout";
import type { LocalAgent } from "../local";
import { parseSlash } from "../models";
import { type ChatPlace, loadPrefs, savePrefs } from "../prefs";
import type { Sheet } from "../sheet";
import { parseShell } from "../shell";
import type { Notice } from "./useNotice";
import type { RepoPicker } from "./useRepoPicker";
import type { OpenModal } from "./useSheets";

export interface Send {
  // What the composer submits: an answer to a typed prompt, a slash command, a ! command, or a message.
  onSubmit: (paneId: string, text: string, images?: ImageContent[]) => void;
  // Messages on their way, by chat (by pane before the chat has a task), shown until the chat has them.
  pending: Map<string, string>;
  // Chats whose stopped run a reply is bringing back.
  reopening: Set<string>;
  // The backend could not deliver a chat's message: it goes back into the pane's composer if it was sent before `at`.
  undelivered: (paneId: string, taskId: string, at: number) => void;
}

// The server's clock can run a little behind this machine's.
const CLOCK_SKEW_MS = 2_000;

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
  openModeSheet,
  pickFor,
  compact,
  openSearch,
  openSettings,
  onChatStarted,
  runShell,
  repos,
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
    localFor: (id: string, pick?: StartPick) => Promise<LocalAgent>;
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
  openModeSheet: (paneId: string, task: Task | undefined) => void;
  pickFor: (paneId: string) => StartPick;
  compact: (
    paneId: string,
    task: Task | undefined,
    instructions: string,
  ) => void;
  openSearch: () => void;
  openSettings: () => void;
  repos: Pick<RepoPicker, "open" | "reposFor">;
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
  const [reopening, setReopening] = useState<Set<string>>(new Set());
  // When each chat's pending reply went out, so an older delivery failure cannot take back a newer message.
  const sentAt = useRef(new Map<string, number>());
  const reopened = (taskId: string, on: boolean): void =>
    setReopening((current) => {
      const next = new Set(current);
      if (on) next.add(taskId);
      else next.delete(taskId);
      return next;
    });

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
    // Notices about this chat show above its composer.
    const here = { paneId, taskId: pane?.taskId ?? null };
    if (slash?.command === "model") {
      openModelSheet(paneId, current);
      return;
    }
    if (slash?.command === "effort") {
      openEffortSheet(paneId, current);
      return;
    }
    if (slash?.command === "mode") {
      openModeSheet(paneId, current);
      return;
    }
    if (slash?.command === "compact") {
      compact(paneId, current, slash.args.trim());
      return;
    }
    if (slash?.command === "new") {
      setLayout((state) => newChatIn(state, paneId));
      return;
    }
    if (slash?.command === "search") {
      openSearch();
      return;
    }
    if (slash?.command === "settings") {
      openSettings();
      return;
    }
    if (slash?.command === "billing") {
      openModal(paneId, billingSheet(loadPrefs().billing), (index) => {
        const billing = BILLINGS[index];
        const blocker = billingBlocker(billing, {
          chatgptAccount: chatgptAccount(),
          claudeToken: loadClaudeToken() !== null,
        });
        if (blocker) return flashNotice(blocker, here);
        savePrefs({ billing });
        flashNotice(billingNotice(billing), here);
      });
      return;
    }
    // With no name, the command comes back with the current one to edit.
    if (slash?.command === "rename") {
      const taskId = pane?.taskId ?? null;
      const title = slash.args.trim();
      const shown = current?.title || pane?.title || "";
      if (!taskId)
        flashNotice("A new chat gets its name from its first message", here);
      else if (!title) composerFor(paneId).setText(`/rename ${shown}`);
      else if (!chats)
        flashNotice("Sign in to rename a chat: type /login", here);
      else {
        // Shown at once; a failed rename puts the old name back, unless a later rename has replaced it.
        setTitles((titles) => new Map(titles).set(taskId, title));
        chats.rename(taskId, title).then(
          (task) => {
            setFresh((tasks) => new Map(tasks).set(task.id, task));
            setLayout((state) => renameTask(state, taskId, taskId, title));
            flashNotice(`Renamed to ${title}`, { taskId });
          },
          (error: unknown) => {
            setTitles((titles) => {
              if (titles.get(taskId) !== title) return titles;
              const next = new Map(titles);
              next.delete(taskId);
              return next;
            });
            flashNotice(`Couldn't rename this chat: ${messageOf(error)}`, {
              taskId,
            });
          },
        );
      }
      return;
    }
    if (slash?.command === "optimize" || slash?.command === "expand") {
      const workspace = workspaceOf(layout, paneId);
      if (!workspace || workspace.root.kind === "pane") {
        flashNotice(
          slash.command === "expand"
            ? "This chat is already full width"
            : "This chat isn't in a workspace. Split it with Ctrl+\\ first",
          here,
        );
      } else if (slash.command === "expand") {
        if (pane?.taskId) setLayout((state) => expandPane(state, paneId));
        else flashNotice("There's no chat here to open yet", here);
      } else {
        const even = optimizeWorkspace(layout, workspace.id);
        if (even) setLayout(even);
        else flashNotice("The panes are already as even as they can be", here);
      }
      return;
    }
    if (slash?.command === "rename-workspace") {
      const workspace = workspaceOf(layout, paneId);
      const name = slash.args.trim();
      if (!workspace || workspace.root.kind === "pane")
        flashNotice(
          "This chat isn't in a workspace. Split it with Ctrl+\\ first",
          here,
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
      if (!taskId) flashNotice("There's nothing to clear yet", here);
      else if (!isLocal(taskId))
        flashNotice(
          "You can't clear a cloud run. Type /new to start a new chat",
          here,
        );
      else
        local.clear(taskId).then(
          () => flashNotice("Cleared this chat", { taskId }),
          (error: unknown) =>
            flashNotice(`Couldn't clear this chat: ${messageOf(error)}`, {
              taskId,
            }),
        );
      return;
    }
    if (slash?.command === "repo") {
      if (
        isLocal(pane?.taskId ?? null) ||
        (!pane?.taskId && places.placeFor(paneId) === "local")
      )
        flashNotice("A local chat works in the folder it runs in", here);
      else repos.open(paneId);
      return;
    }
    if (slash?.command === "local" || slash?.command === "cloud") {
      const mode = slash.command;
      places.setPlace(paneId, mode);
      // An empty pane's prompt already names the new place, so only a pane with a chat open needs the notice.
      if (!pane?.taskId && !pending.has(paneId)) return;
      flashNotice(
        mode === "local"
          ? `New chats run on this machine, in ${process.cwd()}`
          : "New chats run in the cloud",
        here,
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
      return localFor(taskId, pickFor(paneId)).then((session) =>
        session.prompt(text, images),
      );
    };
    if (isLocal(pane?.taskId ?? null)) {
      promptLocal(pane?.taskId as string).catch((error: unknown) => {
        clearPending();
        flashNotice(`Couldn't send: ${messageOf(error)}`, here);
      });
      return;
    }
    // A local chat starts with its task row, so it is never only on this machine; without one, the message stays in the composer.
    if (!pane?.taskId && places.placeFor(paneId) === "local") {
      chats
        .createLocal(text, undefined, localHarnessFor(loadPrefs().billing))
        .then(
          (task) => {
            setFresh((tasks) => new Map(tasks).set(task.id, task));
            onChatStarted(paneId, task.id);
            pendingFor(task.id);
            setLayout((state) =>
              assignTask(
                state,
                paneId,
                task.id,
                task.title || text.slice(0, 80),
              ),
            );
            promptLocal(task.id).catch((error: unknown) => {
              clearPending();
              flashNotice(`Couldn't send: ${messageOf(error)}`, {
                taskId: task.id,
              });
            });
          },
          (error: unknown) => {
            clearPending();
            composerFor(paneId).setText(text);
            flashNotice(
              `Couldn't start the chat: ${messageOf(error)}. Your message is still in the composer.`,
              here,
            );
          },
        );
      return;
    }
    if (!current) {
      const blocker = billingBlocker(loadPrefs().billing, {
        chatgptAccount: chatgptAccount(),
        claudeToken: loadClaudeToken() !== null,
      });
      if (blocker) {
        flashNotice(blocker, here);
        return;
      }
    }
    if (current) sentAt.current.set(current.id, Date.now());
    (current
      ? chats.reply(current, text, images, (resumed) => {
          reopened(current.id, true);
          // The run is queued again, so its status shows before the work list refreshes.
          if (resumed)
            setFresh((tasks) => new Map(tasks).set(resumed.id, resumed));
        })
      : chats.start(
          text,
          images,
          repos.reposFor(paneId),
          cloudHarnessFor(loadPrefs().billing),
          pickFor(paneId),
        )
    ).then(
      (task) => {
        if (current) reopened(current.id, false);
        setFresh((tasks) => new Map(tasks).set(task.id, task));
        if (!current) {
          onChatStarted(paneId, task.id);
          pendingFor(task.id);
          const title = task.title || text.slice(0, 80);
          setLayout((state) => assignTask(state, paneId, task.id, title));
        }
      },
      (error: unknown) => {
        if (current) reopened(current.id, false);
        clearPending();
        composerFor(paneId).putBack(text, images);
        flashNotice(
          `Couldn't send: ${messageOf(error)}. Your message is still in the composer.`,
          here,
        );
      },
    );
  };

  const undelivered = (paneId: string, taskId: string, at: number): void => {
    const text = pending.get(taskId);
    const sent = sentAt.current.get(taskId);
    if (text === undefined || sent === undefined || at < sent - CLOCK_SKEW_MS)
      return;
    sentAt.current.delete(taskId);
    setPending((messages) => {
      const next = new Map(messages);
      next.delete(taskId);
      return next;
    });
    composerFor(paneId).putBack(text, []);
    flashNotice("Your message is back in the composer", { paneId, taskId });
  };

  return { onSubmit, pending, reopening, undelivered };
}
