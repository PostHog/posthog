import type { Task } from "@posthog/shared";
import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";
import { currentRepository, type PiChats } from "../chats";
import { messageOf } from "../errors";
import { type LayoutState, panes, renameTask } from "../layout";
import { type LocalSession, runningLocals } from "../local";
import { LEGACY_PREFIX, LocalChats, linkLocalChats } from "../localChats";
import type { AgentPrompt } from "../prompts";

export interface LocalChatsState {
  // True for a chat that runs on this machine, also before its agent has started.
  isLocal: (taskId: string | null) => taskId is string;
  // The chat's agent, started on first use.
  localFor: (id: string) => Promise<LocalSession>;
  // Agents that have started, by task id.
  localSessions: Map<string, LocalSession>;
  // Restarts the chat's agent on an empty conversation, under the same task and on the same model.
  clear: (id: string) => Promise<void>;
  // This machine's local chats and when each last changed.
  localActive: Map<string, number>;
  // Marks a chat as changed now, before its agent has written its session file.
  markActive: (taskId: string) => void;
  // Re-reads the session files; merged, so a chat without a file yet stays local.
  refreshActive: () => void;
  // What each local chat waits on the user for, and the cursor in each prompt's sheet.
  prompts: Map<string, AgentPrompt[]>;
  promptCursors: Map<string, number>;
  setPromptCursor: (promptId: string, index: number) => void;
}

// Local chats: each is a task with a pi session file on this machine and an agent process started on first use and stopped when the app quits.
export function useLocalChats({
  startLocal,
  chats,
  layout,
  setLayout,
  setFresh,
  flashNotice,
}: {
  startLocal: ((id: string) => Promise<LocalSession>) | undefined;
  chats: PiChats | undefined;
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  setFresh: Dispatch<SetStateAction<Map<string, Task>>>;
  flashNotice: (text: string) => void;
}): LocalChatsState {
  const localChats = useRef(new LocalChats()).current;
  const [localActive, setLocalActive] = useState(() => localChats.list());
  // Chats from before local chats had a task row get one first, so none starts under its old id.
  const [localLinked, setLocalLinked] = useState(false);
  const refreshActive = useRef((): void =>
    setLocalActive((current) => new Map([...current, ...localChats.list()])),
  ).current;
  const isLocal = (taskId: string | null): taskId is string =>
    taskId !== null &&
    (localActive.has(taskId) || taskId.startsWith(LEGACY_PREFIX));
  const [localSessions, setLocalSessions] = useState<Map<string, LocalSession>>(
    new Map(),
  );
  const [prompts, setPrompts] = useState<Map<string, AgentPrompt[]>>(new Map());
  const [promptCursors, setPromptCursors] = useState<Map<string, number>>(
    new Map(),
  );
  // Agents this copy of the hook shows. After a hot swap the agents still run, so the new copy watches them again.
  const watched = useRef(new Set<string>()).current;
  const localFor = (id: string): Promise<LocalSession> => {
    let started = runningLocals.get(id);
    if (!started) {
      if (!startLocal)
        return Promise.reject(new Error("Sign in first: type /login"));
      // Its session file may still be moving to the chat's task id.
      if (!localLinked && id.startsWith(LEGACY_PREFIX))
        return Promise.reject(
          new Error("Local chats are still loading. Try again in a moment"),
        );
      started = startLocal(id);
      runningLocals.set(id, started);
    }
    if (!watched.has(id)) {
      watched.add(id);
      started.then(
        (local) => {
          setLocalSessions((current) => new Map(current).set(id, local));
          local.watchPrompts((list) =>
            setPrompts((current) => new Map(current).set(id, list)),
          );
        },
        (error: unknown) => {
          runningLocals.delete(id);
          watched.delete(id);
          flashNotice(`Couldn't start the local agent: ${messageOf(error)}`);
        },
      );
    }
    return started;
  };

  const clear = async (id: string): Promise<void> => {
    const previous = await runningLocals.get(id)?.catch(() => undefined);
    const models = await previous?.control.models().catch(() => null);
    // Only a model this chat can still pick comes back, never one from a personal pi login.
    const model = models?.available.find(
      (candidate) =>
        candidate.provider === models.current?.provider &&
        candidate.id === models.current.id,
    );
    runningLocals.delete(id);
    watched.delete(id);
    await previous?.stop();
    localChats.archive(id);
    const fresh = await localFor(id);
    if (model) await fresh.control.setModel(model);
  };

  // One pass per sign-in, so a re-run effect never makes a second task for the same chat.
  const linkedFor = useRef<PiChats | null>(null);
  useEffect(() => {
    if (!chats || linkedFor.current === chats) return;
    linkedFor.current = chats;
    void linkLocalChats(localChats, (chat) =>
      chats.createLocal(
        chat.firstMessage || "Local chat",
        chat.cwd ? currentRepository(chat.cwd) : undefined,
      ),
    ).then((linked) => {
      setLayout((state) =>
        [...linked].reduce(
          (next, [legacyId, task]) =>
            renameTask(next, legacyId, task.id, task.title || undefined),
          state,
        ),
      );
      setFresh((current) => {
        const next = new Map(current);
        for (const task of linked.values()) next.set(task.id, task);
        return next;
      });
      refreshActive();
      setLocalLinked(true);
    });
  }, [chats, localChats, refreshActive, setLayout, setFresh]);

  // Local chats in the layout come back after a restart, from their saved pi sessions.
  const localIds = layout.workspaces
    .flatMap((w) => panes(w.root))
    .flatMap((pane) => (isLocal(pane.taskId) ? [pane.taskId] : []))
    .join();
  const startLocalChat = useRef(localFor);
  startLocalChat.current = localFor;
  useEffect(() => {
    if (!startLocal || !localLinked) return;
    for (const id of localIds ? localIds.split(",") : []) {
      void startLocalChat.current(id).catch(() => {});
    }
  }, [localIds, startLocal, localLinked]);

  return {
    isLocal,
    localFor,
    localSessions,
    clear,
    localActive,
    markActive: (taskId) =>
      setLocalActive((current) => new Map(current).set(taskId, Date.now())),
    refreshActive,
    prompts,
    promptCursors,
    setPromptCursor: (promptId, index) =>
      setPromptCursors((current) => new Map(current).set(promptId, index)),
  };
}
