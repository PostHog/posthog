import type { ImageContent } from "@earendil-works/pi-ai";
import type { Task } from "@posthog/shared";
import { type Dispatch, type SetStateAction, useRef, useState } from "react";
import { track } from "../analytics";
import { billingBlocker, cloudHarnessFor, localHarnessFor } from "../billing";
import type { PiChats, StartPick } from "../chats";
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
import { type ChatPlace, loadPrefs } from "../prefs";
import { parseShell } from "../shell";
import type { Account } from "./useAccount";
import type { McpSheet } from "./useMcpSheet";
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
  undelivered: (
    paneId: string,
    taskId: string,
    at: number,
    sandboxGone: boolean,
  ) => void;
  // The chat shows its pending message now, so it is no longer on its way.
  delivered: (taskId: string) => void;
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
  local,
  places,
  composerFor,
  modalFor,
  openModelSheet,
  openEffortSheet,
  openModeSheet,
  pickFor,
  compact,
  openSearch,
  openSettings,
  openHelp,
  onChatStarted,
  runShell,
  repos,
  notice: { flashNotice },
  account,
  mcpSheet,
}: {
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  setFresh: Dispatch<SetStateAction<Map<string, Task>>>;
  setTitles: Dispatch<SetStateAction<Map<string, string>>>;
  chats: PiChats | undefined;
  taskOf: (taskId: string | null) => Task | undefined;
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
  openHelp: () => void;
  repos: Pick<RepoPicker, "open" | "reposFor">;
  onChatStarted: (paneId: string, taskId: string) => void;
  runShell: (
    paneId: string,
    taskId: string | null,
    command: string,
    text: string,
  ) => void;
  notice: Notice;
  account: Pick<
    Account,
    | "openLoginSheet"
    | "openClaudeTokenSheet"
    | "signInToChatgpt"
    | "openBillingSheet"
    | "signOut"
    | "planState"
  >;
  mcpSheet: McpSheet;
}): Send {
  const { isLocal, localFor, markActive } = local;
  const {
    openLoginSheet,
    openClaudeTokenSheet,
    signInToChatgpt,
    openBillingSheet,
    planState,
  } = account;
  const [pending, setPending] = useState<Map<string, string>>(new Map());
  const [reopening, setReopening] = useState<Set<string>>(new Set());
  // When each chat's pending reply went out, so an older delivery failure cannot take back a newer message.
  const sentAt = useRef(new Map<string, number>());
  // Chats whose sandbox answered a delivery with 502 while the server still counts the run as live: the next reply
  // brings the run back instead of sending into the same hole.
  const deadSandboxes = useRef(new Set<string>());
  const reopened = (taskId: string, on: boolean): void =>
    setReopening((current) => {
      const next = new Set(current);
      if (on) next.add(taskId);
      else next.delete(taskId);
      return next;
    });

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
    if (slash)
      track("slash command used", {
        command: slash.command,
        with_args: slash.args.length > 0,
        pane_id: paneId,
        task_id: pane?.taskId ?? null,
      });
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
    if (slash?.command === "settings" || slash?.command === "config") {
      openSettings();
      return;
    }
    if (slash?.command === "help") {
      track("help opened");
      openHelp();
      return;
    }
    if (slash?.command === "billing") {
      openBillingSheet(paneId);
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
    if (slash?.command === "mcp") {
      if (slash.args.trim() === "add") void mcpSheet.addServer(paneId);
      else mcpSheet.open(paneId);
      return;
    }
    if (slash?.command === "login") {
      openLoginSheet(paneId, "Pick the PostHog you sign in to.");
      return;
    }
    if (slash?.command === "logout") {
      setPending(new Map());
      account.signOut(paneId);
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
    const sent = {
      pane_id: paneId,
      chars: text.length,
      images: images.length,
      shell: text.startsWith("!"),
      billing: loadPrefs().billing,
    };
    // React runs these updaters later, so each one captures the key it works on, never the variable.
    const paneKey = pendingKey;
    setPending((messages) => new Map(messages).set(paneKey, text));
    const clearPending = (): void => {
      const key = pendingKey;
      setPending((messages) => {
        const next = new Map(messages);
        next.delete(key);
        return next;
      });
    };
    // A new chat's message moves to its task, so it stays with the chat when the pane shows another.
    const pendingFor = (taskId: string): void => {
      clearPending();
      pendingKey = taskId;
      setPending((messages) => new Map(messages).set(taskId, text));
    };
    const promptLocal = (taskId: string): Promise<void> => {
      track("message sent", {
        ...sent,
        task_id: taskId,
        place: "local",
        new_chat: taskId !== pane?.taskId,
      });
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
      if (billingBlocker(loadPrefs().billing, planState(), "local")) {
        clearPending();
        composerFor(paneId).setText(text);
        if (loadPrefs().billing === "chatgpt")
          signInToChatgpt(paneId, false, () =>
            flashNotice("Logged in to ChatGPT. Press Enter to send.", here),
          );
        else openClaudeTokenSheet(paneId, "", null);
        return;
      }
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
    // A new cloud chat on a plan that still needs a sign-in asks for it here; the message stays in the composer.
    if (!current && billingBlocker(loadPrefs().billing, planState(), "cloud")) {
      clearPending();
      composerFor(paneId).setText(text);
      if (loadPrefs().billing === "chatgpt")
        signInToChatgpt(paneId, true, () =>
          flashNotice("Connected ChatGPT. Press Enter to send.", here),
        );
      else openClaudeTokenSheet(paneId, "", null);
      return;
    }
    if (current) sentAt.current.set(current.id, Date.now());
    track("message sent", {
      ...sent,
      task_id: current?.id ?? null,
      place: "cloud",
      new_chat: !current,
      runtime: current?.runtime ?? null,
    });
    (current
      ? chats.reply(
          current,
          text,
          images,
          (resumed) => {
            track("run reopened", { task_id: current.id, resumed: !!resumed });
            reopened(current.id, true);
            // The run is queued again, so its status shows before the work list refreshes.
            if (resumed)
              setFresh((tasks) => new Map(tasks).set(resumed.id, resumed));
          },
          { sandboxGone: deadSandboxes.current.delete(current.id) },
        )
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

  const undelivered = (
    paneId: string,
    taskId: string,
    at: number,
    sandboxGone: boolean,
  ): void => {
    const text = pending.get(taskId);
    const sent = sentAt.current.get(taskId);
    if (text === undefined || sent === undefined || at < sent - CLOCK_SKEW_MS)
      return;
    sentAt.current.delete(taskId);
    if (sandboxGone) deadSandboxes.current.add(taskId);
    track("message undelivered", {
      pane_id: paneId,
      task_id: taskId,
      sandbox_gone: sandboxGone,
    });
    setPending((messages) => {
      const next = new Map(messages);
      next.delete(taskId);
      return next;
    });
    composerFor(paneId).putBack(text, []);
    flashNotice("Your message is back in the composer", { paneId, taskId });
  };

  const delivered = (taskId: string): void =>
    setPending((messages) => {
      if (!messages.has(taskId)) return messages;
      const next = new Map(messages);
      next.delete(taskId);
      return next;
    });

  return {
    onSubmit,
    pending,
    reopening,
    undelivered,
    delivered,
  };
}
