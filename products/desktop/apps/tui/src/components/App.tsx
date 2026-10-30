import { StdinBuffer } from "@earendil-works/pi-tui";
import type { CloudRegion, Task } from "@posthog/shared";
import {
  Box,
  type DOMElement,
  measureElement,
  useApp,
  useBoxMetrics,
  useInput,
} from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, canRun } from "../actions";
import { REGIONS } from "../auth";
import { currentRepository, type PiChats } from "../chats";
import { ChatView } from "../chatView";
import { copyToClipboard } from "../clipboard";
import { Composer, isAppKey, isTyping } from "../composer";
import {
  activeWorkspace,
  assignTask,
  closeFocused,
  cycleFocus,
  focusPane,
  focusSidebar,
  initialLayout,
  type LayoutNode,
  type LayoutState,
  loadLayout,
  newChat,
  type PaneNode,
  paneIds,
  panes,
  saveLayout,
  splitFocused,
  splitSizes,
} from "../layout";
import type { LocalSession } from "../local";
import {
  type ModelChoice,
  modelSheet,
  type PiControl,
  parseSlash,
  type RunCommand,
} from "../models";
import {
  type Click,
  hitTest,
  type MouseEvents,
  type Box as ScreenBox,
  type Wheel,
} from "../mouse";
import { openUrl } from "../openUrl";
import {
  type AgentPrompt,
  promptId,
  promptReply,
  promptSheet,
  takesText,
} from "../prompts";
import type { CloudRuns } from "../runs";
import { Gesture } from "../selection";
import { moveCursor, type Sheet, type SheetKey, sheetKey } from "../sheet";
import { parseShell } from "../shell";
import { DoublePress, shortcutFor } from "../shortcuts";
import {
  activateRow,
  cursorIndex,
  indicatorFor,
  moveSelection,
  selectionKey,
  sidebarRows,
  type WorkPage,
} from "../sidebar";
import { statusChips } from "../status";
import {
  type PendingShell,
  type ShellLine,
  shellRuns,
  type TranscriptLine,
} from "../transcript";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { HEADER_GAP, Sidebar } from "./Sidebar";

const PAGE_SIZE = 10;
// One shared empty list, so panes with no pending commands keep a stable prop.
const NO_SHELLS: PendingShell[] = [];

const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

interface OpenModal {
  sheet: Sheet;
  index: number;
  choose: (index: number) => void;
  // Runs on Esc, for a sheet whose opener needs to hear about a cancel.
  dismiss?: () => void;
  // Set when the answer is typed in the composer instead of picked from the list.
  submitText?: (text: string) => void;
}
const REFRESH_MS = 10_000;
const CLOSE_CONFIRM_MS = 1_000;
const SEND_ERROR_MS = 8_000;
// Log entries per preloaded run: roughly the last ten messages.
const PREVIEW_ENTRIES = 300;

function boxOf(element: DOMElement): ScreenBox {
  const { x, y, width, height } = measureElement(element);
  return { left: x + 1, top: y + 1, right: x + width, bottom: y + height };
}

// A split draws one line between neighbours: left of each column after the first, above each row after the first.
function dividerProps(divider: "left" | "top" | null) {
  return divider
    ? {
        borderStyle: "single" as const,
        borderColor: "gray",
        borderDimColor: true,
        borderTop: divider === "top",
        borderLeft: divider === "left",
        borderRight: false,
        borderBottom: false,
      }
    : {};
}

export interface Session {
  work: WorkList;
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
  startLocal: (id: string) => Promise<LocalSession>;
}

// Local chats have no server task; panes hold them under an id with this prefix.
const LOCAL_PREFIX = "local:";
const isLocal = (taskId: string | null): taskId is string =>
  taskId?.startsWith(LOCAL_PREFIX) ?? false;

export function App({
  session,
  login,
  logout,
  mouse,
}: {
  // Null while signed out: the layout and composers still work, and /login signs in.
  session: Session | null;
  login: (region: CloudRegion, onAuth: (url: string) => void) => Promise<void>;
  logout: () => void;
  mouse?: MouseEvents;
}): ReactElement {
  const {
    work,
    runs,
    chats,
    control: cloudControl,
    startLocal,
  } = session ?? {};
  // Running local chats, started on first use and stopped when the app closes.
  const locals = useRef(new Map<string, Promise<LocalSession>>());
  const [localSessions, setLocalSessions] = useState<Map<string, LocalSession>>(
    new Map(),
  );
  const localFor = (id: string): Promise<LocalSession> => {
    let started = locals.current.get(id);
    if (!started) {
      if (!startLocal)
        return Promise.reject(new Error("Sign in first: type /login"));
      started = startLocal(id);
      locals.current.set(id, started);
      started.then(
        (local) => {
          setLocalSessions((current) => new Map(current).set(id, local));
          local.watchPrompts((list) =>
            setPrompts((current) => new Map(current).set(id, list)),
          );
        },
        (error: unknown) => {
          locals.current.delete(id);
          flashNotice(`Couldn't start the local agent: ${messageOf(error)}`);
        },
      );
    }
    return started;
  };
  useEffect(
    () => () => {
      for (const started of locals.current.values()) {
        void started.then((local) => local.stop()).catch(() => {});
      }
    },
    [],
  );
  // Cloud runs go through the engine; local chats through their own agent process.
  const control = cloudControl
    ? (taskId: string, runId: string): PiControl =>
        isLocal(taskId)
          ? (localSessions.get(taskId)?.control ?? cloudControl(taskId, runId))
          : cloudControl(taskId, runId)
    : undefined;
  // Where a pane's next new chat runs; /local and /cloud switch it.
  const [modes, setModes] = useState<Map<string, "local" | "cloud">>(new Map());
  const { exit } = useApp();
  const [layout, setLayout] = useState<LayoutState>(loadLayout);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [page, setPage] = useState<WorkPage>({
    tasks: null,
    hasMore: false,
    loadingMore: false,
    error: null,
  });
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [known, setKnown] = useState<Map<string, Task>>(new Map());
  // Tasks this app just started or resumed; they win until the list shows the same run.
  const [fresh, setFresh] = useState<Map<string, Task>>(new Map());
  const [pending, setPending] = useState<Map<string, string>>(new Map());
  // Each pane reports the agent's open action offer; the picker's cursor and dismissals live here.
  const offers = useRef(new Map<string, ActionsLine | null>());
  // Each pane's transcript as last drawn, and the ! commands a cloud run has not logged yet, by task.
  const paneLines = useRef(new Map<string, TranscriptLine[]>());
  const [shells, setShells] = useState<Map<string, PendingShell[]>>(new Map());
  const [pickerIndex, setPickerIndex] = useState<Map<string, number>>(
    new Map(),
  );
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // Modal sheets the app opened, one per pane; they take the pane's keys until closed.
  const [modals, setModals] = useState<Map<string, OpenModal>>(new Map());
  // What each local chat waits on the user for, and the cursor in each prompt's sheet.
  const [prompts, setPrompts] = useState<Map<string, AgentPrompt[]>>(new Map());
  const [promptCursors, setPromptCursors] = useState<Map<string, number>>(
    new Map(),
  );
  // Models: the last list a live run gave us, each task's model, and picks held until a pane's run is live.
  const knownModels = useRef<ModelChoice[] | null>(null);
  const [taskModels, setTaskModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const [heldModels, setHeldModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const appliedHolds = useRef(new Set<string>());
  const closeModal = (paneId: string): void =>
    setModals((current) => {
      const next = new Map(current);
      next.delete(paneId);
      return next;
    });
  // The cursor follows a row's identity, since previewing a chat can move rows.
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Arrows keep walking the sidebar after it hands focus to a chat, until a pane is clicked.
  const [navigating, setNavigating] = useState(false);
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const escapes = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  // Panes whose run is mid-turn, so Esc knows what to stop.
  const runningTurns = useRef(
    new Map<string, { taskId: string; runId: string } | null>(),
  );
  const sidebarBox = useRef<DOMElement | null>(null);
  const paneBoxes = useRef(new Map<string, DOMElement>());
  const chatBoxes = useRef(new Map<string, DOMElement>());
  const prChips = useRef(
    new Map<string, { element: DOMElement; url: string }>(),
  );
  const newChatRepository = useMemo(() => currentRepository(), []);
  const chatArea = useRef<DOMElement | null>(null);
  const area = useBoxMetrics(chatArea);
  const chatViews = useRef(new Map<string, ChatView>());
  // Scrolling happens inside ChatView, so a tick tells React to repaint.
  const [, repaint] = useState(0);
  // Keyed by pane and task, so a pane that switches task starts that chat at its latest message.
  const chatFor = (key: string): ChatView => {
    let chat = chatViews.current.get(key);
    if (!chat) {
      chat = new ChatView();
      chatViews.current.set(key, chat);
    }
    return chat;
  };
  const composers = useRef(new Map<string, Composer>());
  const composerFor = (paneId: string): Composer => {
    let composer = composers.current.get(paneId);
    if (!composer) {
      composer = new Composer(
        () => repaint((tick) => tick + 1),
        (text) => handlers.current.onSubmit(paneId, text),
      );
      composers.current.set(paneId, composer);
    }
    return composer;
  };
  const scrollPane = (paneId: string, lines: number): void => {
    const pane = layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId);
    chatFor(`${paneId}:${pane?.taskId ?? null}`).scrollBy(lines);
    repaint((tick) => tick + 1);
  };

  useEffect(() => saveLayout(layout), [layout]);

  useEffect(() => {
    if (!work) return;
    let cancelled = false;
    const refresh = (): void => {
      work.listRecent(limit).then(
        ({ tasks, hasMore }) => {
          if (!cancelled) {
            setPage({ tasks, hasMore, loadingMore: false, error: null });
          }
        },
        (error: unknown) => {
          if (!cancelled) {
            setPage((current) => ({
              ...current,
              loadingMore: false,
              error: error instanceof Error ? error.message : String(error),
            }));
          }
        },
      );
    };
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [work, limit]);

  // Local chats in the layout come back after a restart, from their saved pi sessions.
  const localIds = layout.workspaces
    .flatMap((w) => panes(w.root))
    .flatMap((pane) => (isLocal(pane.taskId) ? [pane.taskId] : []))
    .join();
  const startLocalChat = useRef(localFor);
  startLocalChat.current = localFor;
  useEffect(() => {
    if (!startLocal) return;
    for (const id of localIds ? localIds.split(",") : []) {
      void startLocalChat.current(id).catch(() => {});
    }
  }, [localIds, startLocal]);

  // Preloads each listed cloud run's recent messages, one at a time, so opening one shows them at once.
  const prefetched = useRef(new Set<string>());
  useEffect(() => {
    const pending = (page.tasks ?? []).flatMap((task) => {
      const run = task.latest_run;
      return run &&
        run.environment !== "local" &&
        !prefetched.current.has(run.id)
        ? [{ taskId: task.id, runId: run.id }]
        : [];
    });
    if (!runs) return;
    for (const { runId } of pending) prefetched.current.add(runId);
    void (async () => {
      for (const { taskId, runId } of pending) {
        await runs.prefetch(taskId, runId, PREVIEW_ENTRIES).catch(() => {
          prefetched.current.delete(runId);
        });
      }
    })();
  }, [runs, page.tasks]);

  // Open tasks outside the recent page are fetched once each, so they keep a title and a transcript.
  const openTaskIds = layout.workspaces
    .flatMap((w) => panes(w.root))
    .flatMap((pane) => (pane.taskId ? [pane.taskId] : []));
  const missing = page.tasks
    ? openTaskIds.filter(
        (id) => !known.has(id) && !page.tasks?.some((task) => task.id === id),
      )
    : [];
  const missingKey = missing.join();
  useEffect(() => {
    if (!work) return;
    for (const taskId of missingKey ? missingKey.split(",") : []) {
      work.get(taskId).then(
        (task) => setKnown((current) => new Map(current).set(taskId, task)),
        () => {},
      );
    }
  }, [work, missingKey]);
  const taskOf = (taskId: string | null): Task | undefined => {
    if (!taskId) return undefined;
    const listed = page.tasks?.find((task) => task.id === taskId);
    const recent = fresh.get(taskId);
    if (recent && recent.latest_run?.id !== listed?.latest_run?.id)
      return recent;
    return listed ?? known.get(taskId);
  };

  const openModal = (
    paneId: string,
    sheet: Sheet,
    choose: (index: number) => void,
  ): void => {
    const current = sheet.items.findIndex((item) => item.current);
    setModals((open) =>
      new Map(open).set(paneId, { sheet, index: Math.max(0, current), choose }),
    );
  };

  const paneTaskId = (paneId: string): string | null =>
    layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId)?.taskId ?? null;

  // A local chat's oldest waiting prompt shows in any pane that has the chat open.
  const promptModal = (taskId: string | null): OpenModal | undefined => {
    const prompt = taskId ? prompts.get(taskId)?.[0] : undefined;
    const local = taskId ? localSessions.get(taskId) : undefined;
    if (!prompt || !local) return undefined;
    const reply = (answer: number | string | null): void => {
      local
        .answer(prompt, promptReply(prompt, answer))
        .catch((error: unknown) =>
          flashNotice(`Couldn't answer: ${messageOf(error)}`),
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
  const modalFor = (paneId: string): OpenModal | undefined =>
    modals.get(paneId) ?? promptModal(paneTaskId(paneId));
  // An editor prompt starts from the text the agent gave it.
  const prefilled = useRef(new Set<string>());
  useEffect(() => {
    for (const pane of layout.workspaces.flatMap((w) => panes(w.root))) {
      const prompt = pane.taskId ? prompts.get(pane.taskId)?.[0] : undefined;
      if (prompt?.kind !== "dialog" || prompt.request.method !== "editor")
        continue;
      if (prefilled.current.has(prompt.request.id)) continue;
      prefilled.current.add(prompt.request.id);
      composerFor(pane.id).setText(prompt.request.prefill ?? "");
    }
  });

  const openModelSheet = (paneId: string, task: Task | undefined): void => {
    const run = task?.latest_run;
    const pane = layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId);
    const localSession = isLocal(pane?.taskId ?? null)
      ? localSessions.get(pane?.taskId as string)
      : undefined;
    const target = localSession
      ? { control: localSession.control, taskId: pane?.taskId as string }
      : task && run && control && indicatorFor(task, false) === "alive"
        ? { control: control(task.id, run.id), taskId: task.id }
        : null;
    if (target) {
      const live = target.control;
      setNotice("Loading models…");
      live.models().then(
        ({ available, current }) => {
          setNotice(null);
          knownModels.current = available;
          if (current)
            setTaskModels((models) =>
              new Map(models).set(target.taskId, current),
            );
          openModal(
            paneId,
            modelSheet(available, current, "Switches this chat's model now."),
            (index) => {
              const model = available[index];
              live.setModel(model).then(
                () =>
                  setTaskModels((models) =>
                    new Map(models).set(target.taskId, model),
                  ),
                (error: unknown) =>
                  flashNotice(`Couldn't switch model: ${messageOf(error)}`),
              );
            },
          );
        },
        (error: unknown) =>
          flashNotice(`Couldn't load models: ${messageOf(error)}`),
      );
      return;
    }
    const available = knownModels.current;
    if (!available) {
      flashNotice(
        "The model list comes from a running chat. Send a message first.",
      );
      return;
    }
    const held =
      heldModels.get(paneId) ?? (task ? taskModels.get(task.id) : undefined);
    openModal(
      paneId,
      modelSheet(
        available,
        held ?? null,
        "Applies once this chat's run starts.",
      ),
      (index) =>
        setHeldModels((models) =>
          new Map(models).set(paneId, available[index]),
        ),
    );
  };

  // Each live run's slash commands, fetched once and handed to the composer of the pane showing it.
  const runCommands = useRef(new Map<string, RunCommand[] | "loading">());
  const commandsShown = useRef(new Map<string, string>());
  const showRunCommands = (
    paneId: string,
    taskId: string,
    runId: string,
  ): void => {
    if (!control) return;
    const commands = runCommands.current.get(runId);
    if (commands === undefined) {
      runCommands.current.set(runId, "loading");
      control(taskId, runId)
        .commands()
        .then(
          (loaded) => {
            runCommands.current.set(runId, loaded);
            showRunCommands(paneId, taskId, runId);
          },
          // No retry: a run that cannot list commands just gets the built-in ones.
          () => runCommands.current.set(runId, []),
        );
      return;
    }
    if (commands === "loading" || commandsShown.current.get(paneId) === runId)
      return;
    commandsShown.current.set(paneId, runId);
    composerFor(paneId).setCommands(commands);
  };

  // A pick made while the run was not live is applied as soon as its sandbox is.
  const onRunLive = (paneId: string, taskId: string, runId: string): void => {
    showRunCommands(paneId, taskId, runId);
    const held = heldModels.get(paneId);
    if (!held || !control || appliedHolds.current.has(runId)) return;
    appliedHolds.current.add(runId);
    control(taskId, runId)
      .setModel(held)
      .then(
        () => {
          setTaskModels((models) => new Map(models).set(taskId, held));
          setHeldModels((models) => {
            const next = new Map(models);
            next.delete(paneId);
            return next;
          });
        },
        (error: unknown) =>
          flashNotice(`Couldn't switch model: ${messageOf(error)}`),
      );
  };

  const flashNotice = (text: string): void => {
    setNotice(text);
    setTimeout(() => setNotice(null), SEND_ERROR_MS);
  };

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
        setNotice("Finish signing in with your browser…");
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
    setPage({ tasks: null, hasMore: false, loadingMore: false, error: null });
    setKnown(new Map());
    setFresh(new Map());
    setPending(new Map());
    flashNotice("Signed out");
  };

  // A ! command runs where the chat's agent runs; a cloud run shows it here until its log has it.
  const runShell = (
    paneId: string,
    taskId: string | null,
    command: string,
    text: string,
  ): void => {
    // When there is nowhere to run it, the command stays in the composer with the reason.
    const run = taskId ? taskOf(taskId)?.latest_run : undefined;
    const blocked = !taskId
      ? "Start a chat first, then run commands with !"
      : isLocal(taskId)
        ? null
        : !run || !control
          ? "This chat has no run to run commands in yet"
          : run.status !== "queued" && run.status !== "in_progress"
            ? "This run has ended. Send a message to start it again, then run commands."
            : null;
    if (blocked || !taskId) {
      composerFor(paneId).setText(text);
      if (blocked) flashNotice(blocked);
      return;
    }
    if (isLocal(taskId)) {
      localFor(taskId)
        .then((local) => local.control.bash(command))
        .catch((error: unknown) =>
          flashNotice(`Couldn't run it: ${messageOf(error)}`),
        );
      return;
    }
    if (!run || !control) return;
    const id = `shell-${globalThis.crypto.randomUUID()}`;
    const seen = shellRuns(paneLines.current.get(paneId) ?? [], command);
    const update = (line: ShellLine | null): void =>
      setShells((current) => {
        const next = new Map(current);
        const others = (current.get(taskId) ?? []).filter(
          (shell) => shell.line.id !== id,
        );
        next.set(taskId, line ? [...others, { line, seen }] : others);
        return next;
      });
    update({ kind: "shell", id, command, status: "in_progress", output: "" });
    control(taskId, run.id)
      .bash(command)
      .then(
        (result) =>
          update({
            kind: "shell",
            id,
            command,
            status:
              result.cancelled || (result.exitCode ?? 0) !== 0
                ? "failed"
                : "completed",
            output: result.output,
          }),
        (error: unknown) => {
          update(null);
          flashNotice(`Couldn't run it: ${messageOf(error)}`);
        },
      );
  };

  const onSubmit = (paneId: string, text: string): void => {
    const pane = layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId);
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
    if (slash?.command === "local" || slash?.command === "cloud") {
      const mode = slash.command;
      setModes((current) => new Map(current).set(paneId, mode));
      flashNotice(
        mode === "local"
          ? `New chats here run on this machine, in ${process.cwd()}`
          : "New chats here run in the cloud",
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
    const localId = isLocal(pane?.taskId ?? null)
      ? (pane?.taskId as string)
      : !pane?.taskId && modes.get(paneId) === "local"
        ? `${LOCAL_PREFIX}${globalThis.crypto.randomUUID()}`
        : null;
    if (localId) {
      if (!pane?.taskId) {
        setLayout((state) =>
          assignTask(state, paneId, localId, text.slice(0, 80)),
        );
      }
      localFor(localId)
        .then((local) => local.prompt(text))
        .catch((error: unknown) => {
          setPending((messages) => {
            const next = new Map(messages);
            next.delete(paneId);
            return next;
          });
          flashNotice(`Couldn't send: ${messageOf(error)}`);
        });
      return;
    }
    (current ? chats.reply(current, text) : chats.start(text)).then(
      (task) => {
        setFresh((tasks) => new Map(tasks).set(task.id, task));
        if (!current) {
          const title = task.title || text.slice(0, 80);
          setLayout((state) => assignTask(state, paneId, task.id, title));
        }
      },
      (error: unknown) => {
        setPending((messages) => {
          const next = new Map(messages);
          next.delete(paneId);
          return next;
        });
        setNotice(
          `Couldn't send: ${error instanceof Error ? error.message : String(error)}`,
        );
        setTimeout(() => setNotice(null), SEND_ERROR_MS);
      },
    );
  };

  const rows = useMemo(
    () =>
      sidebarRows({
        layout,
        work: page,
        collapsed,
        working: new Set(),
        known: new Map([...known, ...fresh]),
        signedIn: session !== null,
      }),
    [layout, page, collapsed, known, fresh, session],
  );
  const selectedIndex = cursorIndex(rows, selected);
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  const activate = (index: number): void => {
    const row = rows[index];
    if (!row) return;
    setSelected(selectionKey(row));
    const next = activateRow(layout, row);
    if (next === "viewMore") {
      setPage((current) => ({ ...current, loadingMore: true }));
      setLimit((current) => current + PAGE_SIZE);
    } else {
      setLayout(next);
    }
  };

  const close = (): void => {
    if (!closeGuard.current.press(Date.now())) {
      const last =
        layout.workspaces.length === 1 && paneIds(workspace.root).length === 1;
      setNotice(`Press again to ${last ? "quit" : "close this chat"}`);
      setTimeout(() => setNotice(null), CLOSE_CONFIRM_MS);
      return;
    }
    setNotice(null);
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
      setCollapsed((current) => {
        const next = new Set(current);
        if (key.leftArrow) next.add(row.workspaceId);
        else next.delete(row.workspaceId);
        return next;
      });
    } else if (key.return) {
      setNavigating(rows[selectedIndex]?.kind === "task");
      activate(selectedIndex);
    }
  });

  // Clicking a row opens it like Enter; clicking elsewhere in the sidebar focuses it; clicking a pane focuses that pane.
  const onClick = (click: Click): void => {
    const sidebar = sidebarBox.current && boxOf(sidebarBox.current);
    if (sidebar && hitTest(click, [["sidebar", sidebar]])) {
      const onScreen = click.row - sidebar.top;
      const index = onScreen === 0 ? 0 : Math.max(0, onScreen - HEADER_GAP);
      const row = rows[index];
      if (
        row?.kind === "task" ||
        row?.kind === "workspace" ||
        row?.kind === "viewMore"
      ) {
        setNavigating(row.kind !== "viewMore");
        activate(index);
      } else {
        setLayout(focusSidebar);
      }
      return;
    }
    const pr = hitTest(
      click,
      [...prChips.current.values()].map(
        ({ element, url }) => [url, boxOf(element)] as [string, ScreenBox],
      ),
    );
    if (pr) {
      openUrl(pr[0]);
      return;
    }
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(click, panes);
    if (hit) {
      setNavigating(false);
      setLayout((current) => focusPane(current, hit[0]));
      const chatBox = chatBoxes.current.get(hit[0]);
      const box = chatBox && boxOf(chatBox);
      const chat = chatFor(`${hit[0]}:${paneTaskId(hit[0])}`);
      if (!box || !hitTest(click, [["chat", box]])) return;
      const link = chat.linkAt(click.row - box.top, click.column - box.left);
      if (link) openUrl(link);
      else if (chat.toggleAt(click.row - box.top)) repaint((tick) => tick + 1);
    }
  };
  const onMove = (move: Click): void => {
    let changed = false;
    for (const [paneId, element] of chatBoxes.current) {
      const box = boxOf(element);
      const row = hitTest(move, [["chat", box]]) ? move.row - box.top : null;
      if (chatFor(`${paneId}:${paneTaskId(paneId)}`).hoverAt(row))
        changed = true;
    }
    if (changed) repaint((tick) => tick + 1);
  };
  const onWheel = (wheel: Wheel): void => {
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(wheel, panes);
    if (hit) scrollPane(hit[0], wheel.delta * 3);
  };
  // Typing in a focused pane goes to its composer; the app's own keys stay with the app.
  // Moves the sidebar cursor and hands focus to that chat, so typing goes straight to it.
  const navigate = (step: 1 | -1): void => {
    const next = moveSelection(rows, selectedIndex, step);
    const row = rows[next];
    setSelected(selectionKey(row));
    const opened = row && activateRow(layout, row);
    if (!opened || opened === "viewMore") {
      setNavigating(false);
      setLayout(focusSidebar);
      return;
    }
    setNavigating(true);
    setLayout(opened);
  };

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
    composer.handleInput(sequence);
  };

  const onModalKey = (
    paneId: string,
    modal: OpenModal,
    key: SheetKey,
  ): void => {
    if (key.kind === "up" || key.kind === "down") {
      const index = moveCursor(
        modal.sheet,
        modal.index,
        key.kind === "up" ? -1 : 1,
      );
      const prompt = modals.has(paneId)
        ? undefined
        : prompts.get(paneTaskId(paneId) ?? "")?.[0];
      if (prompt)
        setPromptCursors((current) =>
          new Map(current).set(promptId(prompt), index),
        );
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
  };

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

  // A press starts a click or, once the pointer moves, a selection in the chat it landed on.
  const gesture = useRef(new Gesture());
  const selecting = useRef<{ chat: ChatView; box: ScreenBox } | null>(null);
  const selectIn = (from: Click, to: Click): void => {
    const target = selecting.current;
    if (!target) return;
    const local = (at: Click): Click => ({
      row: at.row - target.box.top,
      column: at.column - target.box.left,
    });
    target.chat.select(local(from), local(to));
    repaint((tick) => tick + 1);
  };
  const onPress = (at: Click): void => {
    gesture.current.press(at);
    for (const chat of chatViews.current.values()) chat.clearSelection();
    selecting.current = null;
    for (const [paneId, element] of chatBoxes.current) {
      const box = boxOf(element);
      if (hitTest(at, [["chat", box]]))
        selecting.current = {
          chat: chatFor(`${paneId}:${paneTaskId(paneId)}`),
          box,
        };
    }
    repaint((tick) => tick + 1);
  };
  const onDrag = (at: Click): void => {
    const range = gesture.current.drag(at);
    if (range) selectIn(range.from, range.to);
  };
  const onRelease = (at: Click): void => {
    const end = gesture.current.release(at);
    if (end?.kind === "click") onClick(end.at);
    if (end?.kind !== "select" || !selecting.current) return;
    selectIn(end.from, end.to);
    const text = selecting.current.chat.selectedText();
    if (!text.trim()) return;
    copyToClipboard(text);
    flashNotice("Copied to clipboard");
  };

  const handlers = useRef({
    onPress,
    onDrag,
    onRelease,
    onMove,
    onWheel,
    onKey,
    onSubmit,
  });
  handlers.current = {
    onPress,
    onDrag,
    onRelease,
    onMove,
    onWheel,
    onKey,
    onSubmit,
  };

  useEffect(() => {
    if (!mouse) return;
    const press = (at: Click): void => handlers.current.onPress(at);
    const drag = (at: Click): void => handlers.current.onDrag(at);
    const release = (at: Click): void => handlers.current.onRelease(at);
    const wheel = (at: Wheel): void => handlers.current.onWheel(at);
    const move = (at: Click): void => handlers.current.onMove(at);
    const keys = new StdinBuffer();
    keys.on("data", (sequence) => handlers.current.onKey(sequence));
    keys.on("paste", (text) =>
      handlers.current.onKey(`\x1b[200~${text}\x1b[201~`),
    );
    const raw = (data: string): void => keys.process(data);
    mouse.on("press", press);
    mouse.on("drag", drag);
    mouse.on("release", release);
    mouse.on("wheel", wheel);
    mouse.on("move", move);
    mouse.on("keys", raw);
    return () => {
      mouse.off("press", press);
      mouse.off("drag", drag);
      mouse.off("release", release);
      mouse.off("wheel", wheel);
      mouse.off("move", move);
      mouse.off("keys", raw);
      keys.destroy();
    };
  }, [mouse]);

  const titleOf = (pane: PaneNode): string => {
    if (pane.taskId === null) return "New chat";
    return taskOf(pane.taskId)?.title || pane.title || "Untitled";
  };

  // Splits get whole-cell sizes worked out here; flex layout rounds half cells and leaves gaps.
  const renderNode = (
    node: LayoutNode,
    divider: "left" | "top" | null,
    width: number,
    height: number,
  ): ReactElement => {
    if (node.kind === "pane") {
      return (
        <Box
          key={node.id}
          ref={(element) => {
            if (element) paneBoxes.current.set(node.id, element);
            else paneBoxes.current.delete(node.id);
          }}
          width={width}
          height={height}
          flexDirection="column"
          {...dividerProps(divider)}
        >
          <Pane
            title={titleOf(node)}
            paneTaskId={node.taskId}
            task={taskOf(node.taskId)}
            runs={runs ?? null}
            local={
              isLocal(node.taskId) ? localSessions.get(node.taskId) : undefined
            }
            newChatPlace={modes.get(node.id) ?? "cloud"}
            chat={chatFor(`${node.id}:${node.taskId}`)}
            composer={composerFor(node.id)}
            pending={pending.get(node.id) ?? null}
            pendingShells={
              (node.taskId ? shells.get(node.taskId) : undefined) ?? NO_SHELLS
            }
            onLines={(lines) => paneLines.current.set(node.id, lines)}
            onOffer={(offer) => offers.current.set(node.id, offer)}
            picker={{
              index: pickerIndex.get(node.id) ?? 0,
              dismissed,
            }}
            modal={modalFor(node.id) ?? null}
            model={
              heldModels.get(node.id)?.name ??
              (node.taskId ? taskModels.get(node.taskId)?.name : undefined)
            }
            onRunLive={(taskId, runId) => onRunLive(node.id, taskId, runId)}
            onTurn={(turn) => runningTurns.current.set(node.id, turn)}
            chips={
              isLocal(node.taskId) || !node.taskId
                ? statusChips(
                    undefined,
                    newChatRepository,
                    isLocal(node.taskId)
                      ? "local"
                      : (modes.get(node.id) ?? "cloud"),
                  )
                : taskOf(node.taskId)
                  ? statusChips(taskOf(node.taskId), newChatRepository)
                  : []
            }
            onPrChip={(element, url) => {
              if (element && url)
                prChips.current.set(node.id, { element, url });
              else prChips.current.delete(node.id);
            }}
            onChatBox={(element) => {
              if (element) chatBoxes.current.set(node.id, element);
              else chatBoxes.current.delete(node.id);
            }}
            focused={!sidebarFocused && node.id === workspace.focusedPaneId}
          />
        </Box>
      );
    }
    const across = node.direction === "row";
    // This split's own divider takes a row or column before its children share the rest.
    const innerWidth = width - (divider === "left" ? 1 : 0);
    const innerHeight = height - (divider === "top" ? 1 : 0);
    const sizes = splitSizes(
      across ? innerWidth : innerHeight,
      node.children.length,
    );
    return (
      <Box
        key={paneIds(node).join()}
        flexDirection={node.direction}
        width={width}
        height={height}
        {...dividerProps(divider)}
      >
        {node.children.map((child, index) =>
          renderNode(
            child,
            index === 0 ? null : across ? "left" : "top",
            across ? sizes[index] : innerWidth,
            across ? innerHeight : sizes[index],
          ),
        )}
      </Box>
    );
  };

  // A spare row under everything keeps bottom composers off the window's edge.
  return (
    <Box flexGrow={1} paddingBottom={1}>
      <Sidebar
        boxRef={sidebarBox}
        notice={notice}
        rows={rows}
        focused={sidebarFocused}
        selectedIndex={selectedIndex}
        activePaneId={workspace.focusedPaneId}
      />
      <Box ref={chatArea} flexGrow={1}>
        {area.hasMeasured &&
          renderNode(workspace.root, null, area.width, area.height)}
      </Box>
    </Box>
  );
}
