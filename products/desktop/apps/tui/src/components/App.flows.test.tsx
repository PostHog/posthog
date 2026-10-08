import { EventEmitter } from "node:events";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import type { Task } from "@posthog/shared";
import { Box } from "ink";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PiChats } from "../chats";
import { CLAUDE_TOKEN_PATH } from "../claudeToken";
import {
  activeWorkspace,
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
import { loadPrefs } from "../prefs";
import type { AgentPrompt } from "../prompts";
import { type CloudRuns, emptyRunView, type RunView } from "../runs";
import type { ShellResult } from "../shell";
import { renderInTerminal } from "../testing";
import type { WorkList } from "../work";
import { App } from "./App";

vi.mock("../openUrl", () => ({ openUrl: vi.fn(), openImage: vi.fn() }));
const { openUrl } = await import("../openUrl");

const CONFIG = join(homedir(), ".config", "posthog-tui");
// A layout of its own, apart from the other App tests' accounts.
const ACCOUNT = "flow-user";
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
  view = liveView(),
  control = {},
  chats = {},
  layout = openTask(initialLayout(), task.id),
}: {
  task?: Task;
  view?: RunView;
  control?: Partial<PiControl>;
  chats?: Partial<PiChats>;
  layout?: ReturnType<typeof initialLayout>;
} = {}) {
  saveLayout(layout, layoutPath(ACCOUNT));
  const mouse: MouseEvents = new EventEmitter();
  const controlFor = vi.fn(
    () =>
      ({
        commands: async () => [],
        models: async () => ({ available: [], current: null, effort: null }),
        efforts: async () => ({ available: [], current: null }),
        ...control,
      }) as PiControl,
  );
  const { instance, output, type } = renderInTerminal(
    <Box height={30} flexDirection="column">
      <App
        session={{
          account: ACCOUNT,
          work: {
            listRecent: async () => ({ tasks: [task], hasMore: false }),
            get: async () => task,
          } as unknown as WorkList,
          runs: {
            watch: (
              _taskId: string,
              _runId: string,
              onView: (view: RunView) => void,
            ) => {
              onView(view);
              return { stop: () => {}, loadOlder: async () => {} };
            },
            prefetch: async () => {},
          } as unknown as CloudRuns,
          chats: chats as PiChats,
          control: controlFor,
          startLocal: () => Promise.reject(new Error("no local")),
        }}
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
      join(CONFIG, "prefs.json"),
      join(CONFIG, "local", "flow-l1.jsonl"),
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

  it("answers a local agent's permission request from the sheet", async () => {
    const sessions = join(CONFIG, "local");
    mkdirSync(sessions, { recursive: true });
    writeFileSync(join(sessions, "flow-l1.jsonl"), "");
    saveLayout(openTask(initialLayout(), "flow-l1"), layoutPath(ACCOUNT));
    const prompt: AgentPrompt = {
      kind: "acp",
      request: {
        taskRunId: "flow-l1",
        toolCallId: "tc1",
        title: "Run pnpm test",
        options: [
          { optionId: "allow", name: "Allow", kind: "allow_once" },
          { optionId: "reject", name: "Reject", kind: "reject_once" },
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
                  { id: "flow-l1", title: "Local", runtime: "pi" } as Task,
                ],
                hasMore: false,
              }),
            } as unknown as WorkList,
            runs: { prefetch: async () => {} } as unknown as CloudRuns,
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
      await vi.waitFor(() =>
        expect(stripTerminalSequences(output())).toContain("Run pnpm test"),
      );
      // A sheet takes its keys from the raw stream; Ink's own input never sees them.
      await vi.waitFor(() => {
        mouse.emit("keys", "1");
        expect(answer).toHaveBeenCalled();
      });
      expect(vi.mocked(answer).mock.calls[0]?.[1]).toMatchObject({
        optionId: "allow",
      });
    } finally {
      instance.unmount();
    }
  });
});
