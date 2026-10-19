import { EventEmitter } from "node:events";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import type { CloudRegion, Task } from "@posthog/shared";
import { Box } from "ink";
import { type ReactElement, useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PiChats } from "../chats";
import { CLAUDE_TOKEN_PATH } from "../claudeToken";
import type { CodexCloudClient } from "../hooks/useSettings";
import {
  activeWorkspace,
  findPane,
  initialLayout,
  layoutPath,
  loadLayout,
  openTask,
  paneIds,
  saveLayout,
  splitFocused,
} from "../layout";
import type { LocalSession } from "../local";
import type { PiControl } from "../models";
import type { MouseEvents } from "../mouse";
import { loadPrefs, savePrefs } from "../prefs";
import type { AgentPrompt } from "../prompts";
import { type CloudRuns, emptyRunView, type RunView } from "../runs";
import type { ShellResult } from "../shell";
import { startingOptions } from "../starting";
import { renderInTerminal } from "../testing";
import type { WorkList } from "../work";
import { App, type Session } from "./App";
import { FILL_PAGES } from "./Pane";

vi.mock("../openUrl", () => ({ openUrl: vi.fn(), openImage: vi.fn() }));
// pi's ChatGPT login asks for the browser's code, then leaves its tokens in the file it was given.
vi.mock("../chatgpt", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../chatgpt")>()),
  chatgptLogin: vi.fn(
    async (
      ui: { prompt: (question: string) => Promise<string> },
      _signal: AbortSignal,
      path: string,
    ) => {
      const code = await ui.prompt("Paste the code from your browser");
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(
        path,
        JSON.stringify({
          "openai-codex": { access: `access-${code}`, refresh: "refresh" },
        }),
      );
      return "me@example.com";
    },
  ),
}));
const { openUrl } = await import("../openUrl");

const CONFIG = join(homedir(), ".config", "posthog-tui");
// A layout of its own, apart from the other App tests' accounts.
const ACCOUNT = "flow-user";
const WELCOME_ACCOUNT = "welcome-user";
const TOKEN = `sk-ant-oat01-${"x".repeat(40)}`;

const cloudTask = (overrides: Partial<Task> = {}): Task =>
  ({
    id: "c1",
    title: "Cloud chat",
    runtime: "pi",
    latest_run: {
      id: "r1",
      status: "in_progress",
      environment: "cloud",
      state: {},
    },
    ...overrides,
  }) as Task;

// A live cloud run: its agent has reported in and its turn is open, so Esc and ! have something to act on.
const liveView = (): RunView => ({
  ...emptyRunView,
  loaded: true,
  status: "in_progress",
  entries: [
    { type: "pi_run_started", timestamp: new Date().toISOString() },
    {
      type: "pi_event",
      timestamp: new Date().toISOString(),
      event: {
        type: "user_message",
        id: "u1",
        timestamp: Date.now(),
        content: [{ type: "text", text: "Fix the build" }],
      },
    },
  ] as RunView["entries"],
});

// Renders the app signed in, with a 30-row frame as Root gives it, and a cloud task open in the main view.
function cloudApp({
  task = cloudTask(),
  tasks = [task],
  view = liveView(),
  control = {},
  chats = {},
  layout = openTask(initialLayout(), task.id),
  codexCloud,
  runs = {},
}: {
  task?: Task;
  // The work list, when the sidebar needs more than the open task.
  tasks?: Task[];
  view?: RunView;
  control?: Partial<PiControl>;
  chats?: Partial<PiChats>;
  layout?: ReturnType<typeof initialLayout>;
  codexCloud?: CodexCloudClient;
  // Overrides for the run watcher, when a test drives a run's log itself.
  runs?: Partial<CloudRuns>;
} = {}) {
  saveLayout(layout, layoutPath(ACCOUNT));
  const mouse: MouseEvents = new EventEmitter();
  // The chats the panes opened, in order.
  const watched: string[] = [];
  const controlFor = vi.fn(
    () =>
      ({
        commands: async () => [],
        models: async () => ({ available: [], current: null, effort: null }),
        efforts: async () => ({ available: [], current: null }),
        ...control,
      }) as PiControl,
  );
  // One session object: the work list effect keys on its identity, and a new literal each render would cancel the fetch.
  const session: Session = {
    account: ACCOUNT,
    work: {
      listRecent: async () => ({ tasks, hasMore: false }),
      get: async (id: string) => tasks.find((t) => t.id === id) ?? task,
    } as unknown as WorkList,
    runs: {
      watch: (
        taskId: string,
        _runId: string,
        onView: (view: RunView) => void,
      ) => {
        watched.push(taskId);
        onView(view);
        return { stop: () => {}, loadOlder: async () => {} };
      },
      prefetch: async () => {},
      watchPrompts: () => () => {},
      ...runs,
    } as unknown as CloudRuns,
    chats: chats as PiChats,
    control: controlFor,
    startLocal: () => Promise.reject(new Error("no local")),
    codexCloud,
  };
  const { instance, output, type } = renderInTerminal(
    <Box height={30} flexDirection="column">
      <App
        session={session}
        login={async () => {}}
        logout={() => {}}
        mouse={mouse}
      />
    </Box>,
  );
  return {
    output,
    mouse,
    controlFor,
    watched,
    // The terminal's bytes reach both Ink and the raw key stream.
    press: (bytes: string): void => {
      mouse.emit("keys", bytes);
      type(bytes);
    },
    plain: (): string => stripTerminalSequences(output()),
    close: (): void => instance.unmount(),
  };
}

describe("App flows", () => {
  beforeAll(() => initTheme("dark"));
  // Test files share one temporary home and run in parallel, so only what these flows wrote is removed.
  afterEach(() => {
    for (const path of [
      layoutPath(ACCOUNT),
      layoutPath(WELCOME_ACCOUNT),
      layoutPath(),
      join(CONFIG, "prefs.json"),
      join(CONFIG, "local", "flow-l1.jsonl"),
      join(CONFIG, "local", "flow-l2.jsonl"),
      CLAUDE_TOKEN_PATH,
    ])
      rmSync(path, { force: true });
    vi.mocked(openUrl).mockClear();
  });

  it.each<[string, ShellResult | null, string | null, string]>([
    [
      "runs it in the sandbox and shows its output",
      { output: "clean\n", exitCode: 0, cancelled: false },
      null,
      "clean",
    ],
    [
      "says why when the sandbox refuses",
      null,
      "sandbox gone",
      "Couldn't run it: sandbox gone",
    ],
  ])(
    "takes a ! command for a live cloud chat and %s",
    async (_, result, failure, shown) => {
      const bash = vi.fn(async (): Promise<ShellResult> => {
        if (!result) throw new Error(failure ?? "");
        return result;
      });
      const app = cloudApp({ control: { bash } });
      try {
        await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
        app.press("!git status");
        app.press("\r");
        await vi.waitFor(() => expect(bash).toHaveBeenCalledWith("git status"));
        await vi.waitFor(() => expect(app.plain()).toContain(shown));
      } finally {
        app.close();
      }
    },
  );

  it("keeps a ! command in the composer when the chat's run has ended", async () => {
    const task = cloudTask({
      latest_run: {
        id: "r1",
        status: "completed",
        environment: "cloud",
        state: {},
      },
    } as Partial<Task>);
    const bash = vi.fn();
    const app = cloudApp({
      task,
      view: { ...liveView(), status: "completed" },
      control: { bash },
    });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      app.press("!ls");
      app.press("\r");
      await vi.waitFor(() =>
        expect(app.plain()).toContain("This run has ended"),
      );
      expect(bash).not.toHaveBeenCalled();
      expect(app.plain()).toContain("! ls");
    } finally {
      app.close();
    }
  });

  it("stops a live cloud turn once on Esc, and a second Esc clears what is typed", async () => {
    const abort = vi.fn(async () => {});
    const app = cloudApp({ control: { abort } });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      app.press("draft");
      app.press("\x1b");
      await vi.waitFor(() => expect(abort).toHaveBeenCalledTimes(1));
      expect(app.controlFor).toHaveBeenCalledWith("c1", "r1");
      expect(app.plain()).toContain("draft");
      app.press("\x1b");
      await vi.waitFor(() =>
        expect(app.plain().split("draft").length).toBe(
          app.plain().split("draft").length,
        ),
      );
      // The composer no longer holds the draft once the second Esc lands.
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(-2000))).not.toMatch(
          /❯ draft/,
        ),
      );
    } finally {
      app.close();
    }
  });

  it("folds a workspace with ← from one of its chats or a click on its title, and unfolds it with →, Enter or a click", async () => {
    const split = splitFocused(openTask(initialLayout(), "c1"), "row");
    const app = cloudApp({ layout: split });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      // Tab to the sidebar, then down from Today onto the workspace's first chat, which opens it.
      for (const key of ["\t", "\x1b[B"]) {
        app.press(key);
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      app.press("\x1b[D");
      await vi.waitFor(() =>
        expect(app.plain().slice(-3000)).toContain("Workspace #1 (2)"),
      );
      expect(app.plain().slice(-3000)).not.toContain("╰");
      app.press("\x1b[C");
      await vi.waitFor(() => expect(app.plain().slice(-3000)).toContain("╰"));
      // Folded again, the cursor rests on the title while the chat keeps focus, and Enter opens the workspace.
      app.press("\x1b[D");
      await vi.waitFor(() =>
        expect(app.plain().slice(-3000)).toContain("Workspace #1 (2)"),
      );
      app.press("\r");
      await vi.waitFor(() => expect(app.plain().slice(-3000)).toContain("╰"));
      // A click on the title folds it, and a later click (past a double-click's window) opens it again.
      const title = { column: 4, row: 5 };
      app.mouse.emit("press", title);
      app.mouse.emit("release", title);
      await vi.waitFor(() =>
        expect(app.plain().slice(-3000)).toContain("Workspace #1 (2)"),
      );
      await new Promise((resolve) => setTimeout(resolve, 450));
      app.mouse.emit("press", title);
      app.mouse.emit("release", title);
      await vi.waitFor(() => expect(app.plain().slice(-3000)).toContain("╰"));
    } finally {
      app.close();
    }
  });

  it("spins the chat's sidebar dot as soon as a message is sent, and stops once the run has answered it", async () => {
    // An idle run: until it echoes the message, only the pending message says a turn began.
    const idle: RunView = {
      ...emptyRunView,
      loaded: true,
      status: "in_progress",
      entries: [
        { type: "pi_run_started", timestamp: new Date().toISOString() },
      ],
    };
    // The pane and the sidebar's turn tracker each watch the run; both must hear the echo.
    const watchers: ((view: RunView) => void)[] = [];
    const publish = (view: RunView): void => {
      for (const onView of watchers) onView(view);
    };
    const app = cloudApp({
      view: idle,
      chats: { reply: async () => cloudTask() },
      runs: {
        watch: (_t: string, _r: string, onView: (view: RunView) => void) => {
          watchers.push(onView);
          onView(idle);
          return { stop: () => {}, loadOlder: async () => {} };
        },
      },
    });
    try {
      await vi.waitFor(() =>
        expect(app.plain().slice(-3000)).toMatch(/● Cloud chat/),
      );
      app.press("keep going");
      app.press("\r");
      await vi.waitFor(() =>
        expect(app.plain().slice(-3000)).toMatch(/[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Cloud chat/),
      );
      // The run echoes the message and answers it in one go: the turn is over.
      const at = Date.now();
      publish({
        ...idle,
        entries: [
          ...idle.entries,
          {
            type: "pi_event",
            timestamp: new Date(at).toISOString(),
            event: {
              type: "user_message",
              id: "u2",
              timestamp: at,
              content: [{ type: "text", text: "keep going" }],
            },
          },
          {
            type: "pi_event",
            timestamp: new Date(at + 1).toISOString(),
            event: {
              type: "assistant_message_chunk",
              timestamp: at + 1,
              content: { type: "text", text: "Done." },
            },
          },
          {
            type: "pi_event",
            timestamp: new Date(at + 2).toISOString(),
            event: {
              type: "turn_completed",
              timestamp: at + 2,
              stopReason: "stop",
            },
          },
        ] as RunView["entries"],
      });
      await vi.waitFor(
        () => expect(app.plain().slice(-3000)).toMatch(/● Cloud chat/),
        { timeout: 3_000 },
      );
    } finally {
      app.close();
    }
  });

  // On a reload the sidebar used to show every chat off the active workspace with the work list's dot, until the
  // chat was opened and its stream said a turn was open.
  it("spins the dots of chats mid-turn in another workspace and in the list on load, without opening the chat", async () => {
    const other = cloudTask({ id: "c2", title: "Other workspace chat" });
    const listed = cloudTask({ id: "c3", title: "Listed chat" });
    // Workspace 1 holds c2; the main view holds c1 and is active.
    let layout = openTask(initialLayout(), "c2");
    layout = openTask(splitFocused(layout, "row"), "c1");
    layout = openTask(layout, "c1");
    const watched: string[] = [];
    const app = cloudApp({
      layout,
      tasks: [cloudTask(), other, listed],
      runs: {
        watch: (
          taskId: string,
          _runId: string,
          onView: (view: RunView) => void,
        ) => {
          watched.push(taskId);
          onView(liveView());
          return { stop: () => {}, loadOlder: async () => {} };
        },
        // The listed chat is never watched; its prefetched view is what the list reads.
        preview: (taskId: string) => (taskId === "c3" ? liveView() : undefined),
      },
    });
    try {
      await vi.waitFor(
        () => {
          const screen = app.plain().slice(-3000);
          expect(screen).toMatch(/[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Other workspace chat/);
          expect(screen).toMatch(/[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Listed chat/);
        },
        { timeout: 3_000 },
      );
      expect(watched).not.toContain("c3");
    } finally {
      app.close();
    }
  });

  // A long log of tool noise can show a few lines per window; paging until it filled the pane locked the app.
  it("pulls pages into a chat shorter than the pane until the cap, then waits for a scroll", async () => {
    let windowStart = 50_000;
    // The pane and the turn tracker both watch the run.
    const watchers = new Set<(view: RunView) => void>();
    // Each page lands and the chat still fits the pane, so the next one follows, up to the cap.
    const loadOlder = vi.fn(async () => {
      windowStart -= 500;
      for (const onView of watchers) onView({ ...liveView(), windowStart });
    });
    const app = cloudApp({
      view: { ...liveView(), windowStart },
      runs: {
        watch: (_t: string, _r: string, onView: (view: RunView) => void) => {
          watchers.add(onView);
          onView({ ...liveView(), windowStart });
          return { stop: () => watchers.delete(onView), loadOlder };
        },
      },
    });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      await vi.waitFor(() =>
        expect(loadOlder).toHaveBeenCalledTimes(FILL_PAGES),
      );
      await new Promise((resolve) => setTimeout(resolve, 200));
      expect(loadOlder).toHaveBeenCalledTimes(FILL_PAGES);
    } finally {
      app.close();
    }
  });

  it("closes a split pane only on a second Ctrl+C, and quits the last pane the same way", async () => {
    const split = splitFocused(openTask(initialLayout(), "c1"), "row");
    const app = cloudApp({ layout: split });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      expect(
        paneIds(activeWorkspace(loadLayout(layoutPath(ACCOUNT))).root),
      ).toHaveLength(2);
      app.press("\x03");
      await vi.waitFor(() =>
        expect(app.plain()).toContain("Press again to close this chat"),
      );
      expect(
        paneIds(activeWorkspace(loadLayout(layoutPath(ACCOUNT))).root),
      ).toHaveLength(2);
      app.press("\x03");
      await vi.waitFor(() =>
        expect(
          paneIds(activeWorkspace(loadLayout(layoutPath(ACCOUNT))).root),
        ).toHaveLength(1),
      );
    } finally {
      app.close();
    }
  });

  it("opens a new chat outside the split on Ctrl+Shift+N, and the full-screen search on Ctrl+Shift+K", async () => {
    const split = splitFocused(openTask(initialLayout(), "c1"), "row");
    const app = cloudApp({ layout: split });
    const saved = (): ReturnType<typeof loadLayout> =>
      loadLayout(layoutPath(ACCOUNT));
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      // The empty right pane is focused, yet the search takes the whole screen: no pane divider beside it.
      const before = app.output().length;
      app.press("\x1b[107;6u");
      await vi.waitFor(() => {
        const drawn = stripTerminalSequences(app.output().slice(before));
        expect(drawn).toContain("Search tasks");
        expect(drawn).not.toContain("│");
      });
      const closed = app.output().length;
      app.press("\x1b");
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(closed))).toContain(
          "│",
        ),
      );
      app.press("\x1b[110;6u");
      await vi.waitFor(() => {
        const layout = saved();
        expect(activeWorkspace(layout).root.kind).toBe("pane");
        expect(layout.workspaces.map((w) => paneIds(w.root).length)).toEqual([
          2, 1,
        ]);
      });
    } finally {
      app.close();
    }
  });

  it("steps back to the chat a pane left with Ctrl+[, and forward again with Ctrl+]", async () => {
    const split = openTask(
      splitFocused(openTask(initialLayout(), "c1"), "row"),
      "c2",
    );
    const [, right] = paneIds(activeWorkspace(split).root);
    const app = cloudApp({
      layout: split,
      tasks: [cloudTask(), cloudTask({ id: "c2", title: "Other chat" })],
    });
    const rightTask = (): string | null =>
      findPane(loadLayout(layoutPath(ACCOUNT)), right)?.taskId ?? null;
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Other chat"));
      app.press("/new");
      app.press("\r");
      await vi.waitFor(() => expect(rightTask()).toBeNull());
      app.press("\x1b[91;5u");
      await vi.waitFor(() => expect(rightTask()).toBe("c2"));
      app.press("\x1b[93;5u");
      await vi.waitFor(() => expect(rightTask()).toBeNull());
    } finally {
      app.close();
    }
  });

  it("switches the model from the /model sheet by number, and leaves it on Esc", async () => {
    const setModel = vi.fn(async () => {});
    const sol = { provider: "posthog", id: "gpt-6.1-sol", name: "Sol 6.1" };
    const luna = { provider: "posthog", id: "gpt-6.1-luna", name: "Luna 6.1" };
    const app = cloudApp({
      control: {
        models: async () => ({
          available: [sol, luna],
          current: sol,
          effort: null,
        }),
        efforts: async () => ({ available: [], current: null }),
        commands: async () => [],
        setModel,
      },
    });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      app.press("/model");
      app.press("\r");
      await vi.waitFor(() => expect(app.plain()).toContain("Luna 6.1"));
      app.press("\x1b");
      await new Promise((resolve) => setTimeout(resolve, 20));
      expect(setModel).not.toHaveBeenCalled();
      const reopened = app.output().length;
      app.press("/model");
      app.press("\r");
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(reopened))).toContain(
          "Luna 6.1",
        ),
      );
      await vi.waitFor(() => {
        app.press("2");
        expect(setModel).toHaveBeenCalledWith(luna);
      });
      expect(setModel).toHaveBeenCalledTimes(1);
    } finally {
      app.close();
    }
  });

  it("keeps the arrows on an open sheet, not the sidebar, in a chat opened from the sidebar", async () => {
    const sol = { provider: "posthog", id: "gpt-6.1-sol", name: "Sol 6.1" };
    const luna = { provider: "posthog", id: "gpt-6.1-luna", name: "Luna 6.1" };
    const app = cloudApp({
      tasks: [cloudTask(), cloudTask({ id: "c2", title: "Other chat" })],
      control: {
        models: async () => ({
          available: [sol, luna],
          current: sol,
          effort: null,
        }),
        efforts: async () => ({ available: [], current: null }),
        commands: async () => [],
        setModel: async () => {},
      },
    });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Other chat"));
      // Tab to the sidebar, down past New chat and the first chat to the other: each opens, and the arrows keep
      // stepping through chats. Each step waits for its render: the next one reads the cursor the last one left.
      for (const key of ["\t", "\x1b[B", "\x1b[B", "\x1b[B"]) {
        app.press(key);
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
      expect(app.watched.at(-1)).toBe("c2");
      app.press("/model");
      app.press("\r");
      await vi.waitFor(() => expect(app.plain()).toContain("Luna 6.1"));
      const opened = app.watched.length;

      app.press("\x1b[A");
      await new Promise((resolve) => setTimeout(resolve, 50));

      expect(app.watched.length).toBe(opened);
    } finally {
      app.close();
    }
  });

  it("opens the PR from a click on the pane header's chip", async () => {
    const task = cloudTask({
      latest_run: {
        id: "r1",
        status: "in_progress",
        environment: "cloud",
        state: {},
        pr_url: "https://github.com/PostHog/posthog/pull/9",
      },
    } as unknown as Partial<Task>);
    const app = cloudApp({ task });
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("#9"));
      const line =
        app
          .plain()
          .split("\n")
          .find((row) => row.includes("#9")) ?? "";
      const column = line.indexOf("#9") + 2;
      app.mouse.emit("press", { column, row: 1 });
      app.mouse.emit("release", { column, row: 1 });
      await vi.waitFor(() =>
        expect(openUrl).toHaveBeenCalledWith(
          "https://github.com/PostHog/posthog/pull/9",
        ),
      );
    } finally {
      app.close();
    }
  });

  it("picks repositories for a pane's next cloud chat with /repo", async () => {
    const start = vi.fn(
      async (_text: string, _images: unknown, repos: string[]) =>
        cloudTask({ id: "c2", title: `New chat on ${repos.join(",")}` }),
    );
    const app = cloudApp({
      layout: initialLayout(),
      chats: {
        searchRepositories: vi.fn(async (query: string) =>
          ["PostHog/posthog", "PostHog/charts"].filter((repo) =>
            repo.includes(query),
          ),
        ),
        start,
      } as unknown as Partial<PiChats>,
    });
    try {
      await vi.waitFor(() =>
        expect(app.plain()).toContain("start a cloud run"),
      );
      app.press("/repo");
      app.press("\r");
      await vi.waitFor(() => expect(app.plain()).toContain("PostHog/charts"));
      const typed = app.output().length;
      app.press("charts");
      // The ticked folder repository stays first, so the match lands under it.
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(typed))).toMatch(
          /Search: charts[\s\S]*✔ PostHog\/posthog[\s\S]*· PostHog\/charts/,
        ),
      );
      app.press("\x1b[B");
      app.press(" ");
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(typed))).toContain(
          "✔ PostHog/charts",
        ),
      );
      app.press("\r");
      await vi.waitFor(() =>
        expect(app.plain()).toContain("clone PostHog/posthog, PostHog/charts"),
      );
      const paneId = activeWorkspace(
        loadLayout(layoutPath(ACCOUNT)),
      ).focusedPaneId;
      expect(loadPrefs().paneRepositories[paneId]).toEqual([
        "PostHog/posthog",
        "PostHog/charts",
      ]);
      app.press("hello");
      app.press("\r");
      await vi.waitFor(() => expect(start).toHaveBeenCalled());
      expect(vi.mocked(start).mock.calls[0]?.[2]).toEqual([
        "PostHog/posthog",
        "PostHog/charts",
      ]);
    } finally {
      app.close();
    }
  });

  it("starts a cloud chat on a plan with the model its header says it starts on", async () => {
    const access = `h.${Buffer.from(
      JSON.stringify({
        "https://api.openai.com/profile": { email: "me@example.com" },
      }),
    ).toString("base64url")}.s`;
    mkdirSync(join(homedir(), ".pi", "agent"), { recursive: true });
    writeFileSync(
      join(homedir(), ".pi", "agent", "auth.json"),
      JSON.stringify({ "openai-codex": { type: "oauth", access } }),
    );
    savePrefs({ billing: "chatgpt" });
    const start = vi.fn(async () => cloudTask({ id: "c3" }));
    const app = cloudApp({
      layout: initialLayout(),
      chats: { start } as unknown as Partial<PiChats>,
      // A cloud Codex run needs the ChatGPT account PostHog holds, not pi's login.
      codexCloud: {
        get: async () => ({ status: "connected", email: "me@example.com" }),
      } as unknown as CodexCloudClient,
    });
    try {
      const model = startingOptions("chatgpt", "cloud").model;
      await vi.waitFor(() =>
        expect(app.plain()).toContain(`New chat · ${model?.name}`),
      );
      app.press("hello");
      app.press("\r");
      await vi.waitFor(() => expect(start).toHaveBeenCalled());
      expect(vi.mocked(start).mock.calls[0]?.slice(3)).toEqual([
        "codex",
        { model: model?.id },
      ]);
    } finally {
      app.close();
    }
  });

  it("connects ChatGPT for cloud runs from the billing sheet, with pi's question on a sheet", async () => {
    const connect = vi.fn(async () => ({
      status: "connected",
      email: "me@example.com",
    }));
    const app = cloudApp({
      layout: initialLayout(),
      codexCloud: {
        get: async () => ({ status: "disconnected" }),
        connect,
        disconnect: async () => {},
      } as unknown as CodexCloudClient,
    });
    try {
      await vi.waitFor(() =>
        expect(app.plain()).toContain("start a cloud run"),
      );
      app.press("/billing");
      app.press("\r");
      await vi.waitFor(() =>
        expect(app.plain()).toContain("What new chats run on"),
      );
      app.press("2");
      await vi.waitFor(() =>
        expect(app.plain()).toContain("Paste the code from your browser"),
      );
      app.press("abc");
      app.press("\r");
      await vi.waitFor(() =>
        expect(connect).toHaveBeenCalledWith({
          access_token: "access-abc",
          refresh_token: "refresh",
        }),
      );
      await vi.waitFor(() => expect(loadPrefs().billing).toBe("chatgpt"));
      await vi.waitFor(() =>
        expect(app.plain().slice(-1500)).toContain("ChatGPT subscription"),
      );
    } finally {
      app.close();
    }
  });

  it("shows every shortcut on /help and closes it on Esc", async () => {
    const app = cloudApp({ layout: initialLayout() });
    try {
      await vi.waitFor(() =>
        expect(app.plain()).toContain("start a cloud run"),
      );
      app.press("/help");
      app.press("\r");
      await vi.waitFor(() =>
        expect(app.plain()).toContain("Keyboard shortcuts"),
      );
      expect(app.plain().slice(-3000)).toContain("Split side by side");
      // Every built-in command, from the composer's own list.
      expect(app.plain().slice(-3000)).toContain("/mcp");
      app.press("\x1b");
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(-3000))).toContain(
          "start a cloud run",
        ),
      );
    } finally {
      app.close();
    }
  });

  it("saves a pasted Claude token from settings and closes on Esc", async () => {
    const app = cloudApp({ layout: initialLayout() });
    try {
      await vi.waitFor(() =>
        expect(app.plain()).toContain("start a cloud run"),
      );
      app.press("\x1b[59;5u");
      await vi.waitFor(() => expect(app.plain()).toContain("Settings"));
      app.press("\x1b[B");
      app.press("\r");
      app.press(TOKEN);
      app.press("\r");
      await vi.waitFor(() =>
        expect(readFileSync(CLAUDE_TOKEN_PATH, "utf8").trim()).toBe(TOKEN),
      );
      app.press("\x1b");
      await vi.waitFor(() =>
        expect(stripTerminalSequences(app.output().slice(-3000))).toContain(
          "start a cloud run",
        ),
      );
    } finally {
      app.close();
    }
  });

  // Renders a first run signed out, whose sign-in lands the session Root would build.
  function welcomeApp(codexCloud?: CodexCloudClient) {
    saveLayout(initialLayout());
    const mouse: MouseEvents = new EventEmitter();
    const login = vi.fn(async (_region: CloudRegion) => {});
    function Host(): ReactElement {
      const [session, setSession] = useState<Session | null>(null);
      return (
        <App
          session={session}
          login={async (region) => {
            await login(region);
            setSession({
              account: WELCOME_ACCOUNT,
              work: {
                listRecent: async () => ({ tasks: [], hasMore: false }),
              } as unknown as WorkList,
              runs: {
                prefetch: async () => {},
                watchPrompts: () => () => {},
              } as unknown as CloudRuns,
              chats: {} as PiChats,
              control: () => ({}) as PiControl,
              startLocal: () => Promise.reject(new Error("no local")),
              codexCloud,
            });
          }}
          logout={() => {}}
          mouse={mouse}
          handoff={(run) => run()}
        />
      );
    }
    const { instance, output } = renderInTerminal(
      <Box height={30} flexDirection="column">
        <Host />
      </Box>,
    );
    return {
      mouse,
      login,
      plain: (): string => stripTerminalSequences(output()),
      close: (): void => instance.unmount(),
    };
  }

  // Through the welcome to the billing sheet, with the app's chrome held back until then.
  async function welcomeToBilling(app: ReturnType<typeof welcomeApp>) {
    await vi.waitFor(() => expect(app.plain()).toContain("Sign in to PostHog"));
    expect(loadPrefs().welcomed).toBe(true);
    expect(app.plain()).toContain("Welcome to PostHog");
    expect(app.plain()).not.toContain("All chats");
    expect(app.plain()).not.toContain("New chat");
    app.mouse.emit("keys", "\r");
    await vi.waitFor(() => expect(app.login).toHaveBeenCalledWith("us"));
    await vi.waitFor(() =>
      expect(app.plain()).toContain("What new chats run on"),
    );
  }

  it("asks a signed-out run that was welcomed before to sign in, with the regions, and skips the rest of the welcome", async () => {
    savePrefs({ welcomed: true });
    const app = welcomeApp();
    try {
      await vi.waitFor(() =>
        expect(app.plain()).toContain("Sign in to PostHog"),
      );
      expect(app.plain()).toMatch(/1\. .*US/);
      expect(app.plain()).toMatch(/2\. .*EU/);
      // The app's chrome stays, unlike a first run's welcome screen.
      expect(app.plain()).toContain("All chats");
      expect(app.plain()).not.toContain("Welcome to PostHog");
      app.mouse.emit("keys", "\r");
      await vi.waitFor(() => expect(app.login).toHaveBeenCalledWith("us"));
      // Signed in: the chrome, not the billing sheet a first run goes on to.
      await vi.waitFor(() => expect(app.plain()).toContain("All chats"));
      expect(app.plain()).not.toContain("What new chats run on");
    } finally {
      app.close();
    }
  });

  it("opens the sign-in sheet on /logout, so the next sign-in is one Enter away", async () => {
    const app = cloudApp();
    try {
      await vi.waitFor(() => expect(app.plain()).toContain("Fix the build"));
      app.press("/logout");
      app.press("\r");
      await vi.waitFor(() =>
        expect(app.plain().slice(-3000)).toContain("Sign in to PostHog"),
      );
      expect(app.plain().slice(-3000)).toMatch(/1\. .*US/);
    } finally {
      app.close();
    }
  });

  it("welcomes a first run: sign in, pick who pays, and get the Claude token that plan needs", async () => {
    // A `claude` on PATH whose setup-token prints a token, as the real one does after the browser sign-in.
    const bin = mkdtempSync(join(tmpdir(), "welcome-claude-"));
    writeFileSync(
      join(bin, "claude"),
      `#!/bin/sh\necho "Browser opened"\necho "Your token: ${TOKEN}"\n`,
    );
    chmodSync(join(bin, "claude"), 0o755);
    const path = process.env.PATH;
    process.env.PATH = `${bin}${delimiter}${path ?? ""}`;
    const app = welcomeApp();
    const { mouse, plain } = app;
    try {
      await welcomeToBilling(app);
      mouse.emit("keys", "3");
      await vi.waitFor(() =>
        expect(plain()).toContain("Run claude setup-token"),
      );
      // A pasted token that is not one asks again.
      mouse.emit("keys", "2");
      await vi.waitFor(() =>
        expect(plain().slice(-1500)).toContain("❯ 2. Paste a token"),
      );
      mouse.emit("keys", "not-a-token");
      mouse.emit("keys", "\r");
      await vi.waitFor(() =>
        expect(plain().slice(-1500)).toContain("Paste the full token"),
      );
      expect(loadPrefs().billing).toBe("posthog");
      // Running the command takes the token from what it prints.
      mouse.emit("keys", "1");
      // The fake `claude` is spawned and read on the terminal handoff, which can take over a second on a busy box.
      await vi.waitFor(
        () =>
          expect(readFileSync(CLAUDE_TOKEN_PATH, "utf8").trim()).toBe(TOKEN),
        { timeout: 5_000 },
      );
      expect(loadPrefs().billing).toBe("anthropic");
      await vi.waitFor(() =>
        expect(plain().slice(-1200)).toContain("• Anthropic subscription"),
      );
      expect(plain().slice(-1200)).toContain("All chats");
    } finally {
      process.env.PATH = path;
      app.close();
    }
  });

  it("welcomes a first run onto the ChatGPT plan with the account PostHog keeps for cloud runs", async () => {
    const connect = vi.fn(async () => ({
      status: "connected",
      email: "me@example.com",
    }));
    const app = welcomeApp({
      get: async () => ({ status: "disconnected" }),
      connect,
      disconnect: async () => {},
    } as unknown as CodexCloudClient);
    const { mouse, plain } = app;
    try {
      await welcomeToBilling(app);
      mouse.emit("keys", "2");
      await vi.waitFor(() =>
        expect(plain()).toContain("Paste the code from your browser"),
      );
      mouse.emit("keys", "abc");
      mouse.emit("keys", "\r");
      await vi.waitFor(() =>
        expect(connect).toHaveBeenCalledWith({
          access_token: "access-abc",
          refresh_token: "refresh",
        }),
      );
      await vi.waitFor(() => expect(loadPrefs().billing).toBe("chatgpt"));
      await vi.waitFor(() =>
        expect(plain().slice(-1200)).toContain("• ChatGPT subscription"),
      );
    } finally {
      app.close();
    }
  });

  // Local agents live in a global map by task id, so each case gets its own chat.
  it.each([
    ["the picked option", "flow-l1", ["1"], { optionId: "allow" }],
    // An option that asks what to do instead takes the text from the composer.
    [
      "the typed feedback",
      "flow-l2",
      ["2", "use pnpm", "\r"],
      { optionId: "reject", customInput: "use pnpm" },
    ],
  ])(
    "answers a local agent's permission request from the sheet with %s",
    async (_name, taskId, keys, expected) => {
      const sessions = join(CONFIG, "local");
      mkdirSync(sessions, { recursive: true });
      writeFileSync(join(sessions, `${taskId}.jsonl`), "");
      saveLayout(openTask(initialLayout(), taskId), layoutPath(ACCOUNT));
      const prompt: AgentPrompt = {
        kind: "acp",
        request: {
          taskRunId: taskId,
          toolCallId: "tc1",
          title: "Run pnpm test",
          options: [
            { optionId: "allow", name: "Allow", kind: "allow_once" },
            {
              optionId: "reject",
              name: "No, and tell the agent what to do differently",
              kind: "reject_once",
              _meta: { customInput: true },
            },
          ],
        },
      };
      const answer = vi.fn(async (_prompt: AgentPrompt, _reply: unknown) => {});
      const local = {
        watch: (onView: (view: RunView) => void) => {
          onView({ ...emptyRunView, loaded: true, status: "in_progress" });
          return () => {};
        },
        watchPrompts: (onPrompts: (prompts: AgentPrompt[]) => void) => {
          onPrompts([prompt]);
          return () => {};
        },
        prompt: async () => {},
        answer,
        stop: async () => {},
        control: {
          models: async () => ({ available: [], current: null }),
          efforts: async () => ({ available: [], current: null }),
          commands: async () => [],
        },
      } as unknown as LocalSession;
      const mouse: MouseEvents = new EventEmitter();
      const { instance, output } = renderInTerminal(
        <Box height={30} flexDirection="column">
          <App
            session={{
              account: ACCOUNT,
              work: {
                listRecent: async () => ({
                  tasks: [
                    { id: taskId, title: "Local", runtime: "pi" } as Task,
                  ],
                  hasMore: false,
                }),
              } as unknown as WorkList,
              runs: {
                prefetch: async () => {},
                watchPrompts: () => () => {},
              } as unknown as CloudRuns,
              chats: {} as PiChats,
              control: () => ({}) as PiControl,
              startLocal: async () => local,
            }}
            login={async () => {}}
            logout={() => {}}
            mouse={mouse}
          />
        </Box>,
      );
      try {
        // The first message starts the agent, whose request then lands on the sheet.
        await vi.waitFor(() =>
          expect(stripTerminalSequences(output())).toContain("Local"),
        );
        mouse.emit("keys", "hi");
        mouse.emit("keys", "\r");
        await vi.waitFor(() =>
          expect(stripTerminalSequences(output())).toContain("Run pnpm test"),
        );
        // A sheet takes its keys from the raw stream; Ink's own input never sees them.
        mouse.emit("keys", keys[0]);
        if (keys.length > 1) {
          await vi.waitFor(() =>
            expect(stripTerminalSequences(output())).toContain(
              "Type what to do instead",
            ),
          );
          for (const key of keys.slice(1)) mouse.emit("keys", key);
        }
        await vi.waitFor(() => expect(answer).toHaveBeenCalled());
        expect(vi.mocked(answer).mock.calls[0]?.[1]).toMatchObject(expected);
      } finally {
        instance.unmount();
      }
    },
  );
});
