import { EventEmitter } from "node:events";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import type { Task } from "@posthog/shared";
import { Box, renderToString } from "ink";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PiChats } from "../chats";
import {
  activeWorkspace,
  allPanes,
  focusPane,
  initialLayout,
  layoutPath,
  loadLayout,
  openTask,
  paneIds,
  saveLayout,
  splitFocused,
} from "../layout";
import type { LocalSession } from "../local";
import { type PiControl, STARTING_MODEL } from "../models";
import type { MouseEvents } from "../mouse";
import { loadPrefs } from "../prefs";
import { type CloudRuns, emptyRunView } from "../runs";
import { renderInTerminal } from "../testing";
import type { TodayClient } from "../today";
import type { WorkList } from "../work";
import { App } from "./App";

const task = (): Task =>
  ({
    id: "t1",
    title: "Fix it",
    runtime: "pi",
    latest_run: {
      id: "r1",
      status: "completed",
      environment: "cloud",
      state: {},
    },
  }) as Task;

describe("App", () => {
  afterEach(() => vi.useRealTimers());

  it("shows the sidebar", () => {
    const work = {
      listRecent: () => new Promise(() => {}),
    } as unknown as WorkList;
    expect(
      renderToString(
        <App
          session={{
            work,
            runs: {} as CloudRuns,
            chats: {} as PiChats,
            control: () => ({}) as PiControl,
            startLocal: () => Promise.reject(new Error("no local")),
          }}
          login={async () => {}}
          logout={() => {}}
        />,
      ),
    ).toContain("PostHog");
  });

  it("keeps watching an open run across list refreshes", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    saveLayout(openTask(initialLayout(), "t1"));
    // Every refresh returns fresh task objects, as the API does.
    const work = {
      listRecent: async () => ({ tasks: [task()], hasMore: false }),
      get: vi.fn(),
    } as unknown as WorkList;
    const runs = {
      watch: vi.fn(() => ({ stop: () => {}, loadOlder: async () => {} })),
      prefetch: vi.fn(async () => {}),
    } as unknown as CloudRuns;

    const { instance } = renderInTerminal(
      <App
        session={{
          work,
          runs: runs,
          chats: {} as PiChats,
          control: () => ({}) as PiControl,
          startLocal: () => Promise.reject(new Error("no local")),
        }}
        login={async () => {}}
        logout={() => {}}
      />,
    );
    // The pane watches the run to draw it, and the sidebar to know when its turn ends.
    await vi.waitFor(() => expect(runs.watch).toHaveBeenCalledTimes(2));
    for (let refresh = 0; refresh < 3; refresh++) {
      await vi.advanceTimersByTimeAsync(10_000);
    }
    instance.unmount();

    expect(runs.watch).toHaveBeenCalledTimes(2);
  });

  it("shows a local chat that has a task row and no run", async () => {
    const sessions = join(homedir(), ".config", "posthog-tui", "local");
    mkdirSync(sessions, { recursive: true });
    writeFileSync(join(sessions, "t2.jsonl"), "");
    saveLayout(openTask(initialLayout(), "t2"));
    const work = {
      listRecent: async () => ({
        tasks: [{ id: "t2", title: "Local", runtime: "pi" } as Task],
        hasMore: false,
      }),
    } as unknown as WorkList;
    const local = {
      watch: (onView: (view: typeof emptyRunView) => void) => {
        onView({
          ...emptyRunView,
          loaded: true,
          error: "from the local agent",
        });
        return () => {};
      },
      watchPrompts: () => () => {},
      stop: async () => {},
    } as unknown as LocalSession;

    const { instance, output } = renderInTerminal(
      <App
        session={{
          work,
          runs: { prefetch: async () => {} } as unknown as CloudRuns,
          chats: {} as PiChats,
          control: () => ({}) as PiControl,
          startLocal: async () => local,
        }}
        login={async () => {}}
        logout={() => {}}
      />,
    );
    try {
      await vi.waitFor(() =>
        expect(output()).toContain("from the local agent"),
      );
    } finally {
      instance.unmount();
      rmSync(sessions, { recursive: true });
    }
  });

  it("shows today's briefing in the main view's new chat, under a Today row", async () => {
    saveLayout(initialLayout());
    const today = {
      load: async () => ({
        kind: "ready",
        firstName: "Harley",
        briefing: {
          status: "ready",
          headline: "One report needs your attention.",
          paragraphs: [],
          items: [],
          more_reports_count: 0,
        },
      }),
    } as unknown as TodayClient;
    const { instance, output } = renderInTerminal(
      <App
        session={{
          work: {
            listRecent: () => new Promise(() => {}),
          } as unknown as WorkList,
          runs: { prefetch: async () => {} } as unknown as CloudRuns,
          chats: {} as PiChats,
          control: () => ({}) as PiControl,
          startLocal: () => Promise.reject(new Error("no local")),
          today,
        }}
        login={async () => {}}
        logout={() => {}}
      />,
    );
    try {
      await vi.waitFor(() => {
        const screen = stripTerminalSequences(output());
        expect(screen).toContain("☼ Today");
        expect(screen).toContain(", Harley.");
      });
    } finally {
      instance.unmount();
    }
  });

  it("names the model a new chat starts on, before any /model pick", async () => {
    saveLayout(initialLayout());
    const { instance, output } = renderInTerminal(
      <App
        session={{
          work: {
            listRecent: () => new Promise(() => {}),
          } as unknown as WorkList,
          runs: { prefetch: async () => {} } as unknown as CloudRuns,
          chats: {} as PiChats,
          control: () => ({}) as PiControl,
          startLocal: () => Promise.reject(new Error("no local")),
        }}
        login={async () => {}}
        logout={() => {}}
      />,
    );
    try {
      await vi.waitFor(() =>
        expect(output()).toContain(`New chat · ${STARTING_MODEL.name}`),
      );
    } finally {
      instance.unmount();
    }
  });

  it("names the model and effort a live chat reports, not the model it would start on", async () => {
    const sessions = join(homedir(), ".config", "posthog-tui", "local");
    mkdirSync(sessions, { recursive: true });
    writeFileSync(join(sessions, "t3.jsonl"), "");
    saveLayout(openTask(initialLayout(), "t3"));
    const local = {
      watch: (onView: (view: typeof emptyRunView) => void) => {
        onView({ ...emptyRunView, loaded: true, status: "in_progress" });
        return () => {};
      },
      watchPrompts: () => () => {},
      stop: async () => {},
      control: {
        models: async () => ({
          available: [],
          current: { provider: "posthog", id: "gpt-6.1-sol", name: "Sol 6.1" },
        }),
        efforts: async () => ({ available: ["low", "high"], current: "high" }),
        commands: async () => [],
      },
    } as unknown as LocalSession;

    const { instance, output } = renderInTerminal(
      <App
        session={{
          work: {
            listRecent: async () => ({
              tasks: [{ id: "t3", title: "Local", runtime: "pi" } as Task],
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
      />,
    );
    try {
      await vi.waitFor(() =>
        expect(output()).toContain("Local · Sol 6.1 (high)"),
      );
    } finally {
      instance.unmount();
      rmSync(sessions, { recursive: true });
    }
  });

  it("keeps a chat's sidebar spinner going after it leaves the screen, until its turn ends", async () => {
    initTheme("dark");
    const sessions = join(homedir(), ".config", "posthog-tui", "local");
    mkdirSync(sessions, { recursive: true });
    writeFileSync(join(sessions, "t4.jsonl"), "");
    saveLayout(openTask(initialLayout(), "t4"));
    const event = (second: number, fields: Record<string, unknown>) => ({
      type: "pi_event",
      timestamp: new Date(second * 1000).toISOString(),
      event: { timestamp: second * 1000, ...fields },
    });
    const midTurn = {
      ...emptyRunView,
      loaded: true,
      status: "in_progress",
      entries: [
        event(1, {
          type: "user_message",
          id: "u1",
          content: [{ type: "text", text: "Rename the helper" }],
        }),
        event(2, {
          type: "assistant_message_chunk",
          content: { type: "text", text: "On it." },
        }),
      ],
    } as typeof emptyRunView;
    const watchers = new Set<(view: typeof emptyRunView) => void>();
    const local = {
      watch: (onView: (view: typeof emptyRunView) => void) => {
        watchers.add(onView);
        onView(midTurn);
        return () => watchers.delete(onView);
      },
      watchPrompts: () => () => {},
      stop: async () => {},
      control: {
        models: async () => ({ available: [], current: null }),
        efforts: async () => ({ available: [], current: null }),
        commands: async () => [],
      },
    } as unknown as LocalSession;
    const { instance, output, type } = renderInTerminal(
      <App
        session={{
          work: {
            listRecent: async () => ({
              tasks: [{ id: "t4", title: "Local", runtime: "pi" } as Task],
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
      />,
    );
    const spinning = /[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏] Local/;
    const drawnSince = (mark: number): string =>
      stripTerminalSequences(output().slice(mark));
    try {
      await vi.waitFor(() => expect(drawnSince(0)).toMatch(spinning), {
        timeout: 3_000,
      });
      // Ctrl+N puts a new chat on screen in its place.
      type("\x0e");
      await vi.waitFor(() => expect(watchers.size).toBe(1));
      const left = output().length;
      await vi.waitFor(() => expect(drawnSince(left)).toMatch(spinning));

      for (const onView of watchers)
        onView({
          ...midTurn,
          entries: [
            ...midTurn.entries,
            event(3, { type: "turn_completed", stopReason: "stop" }),
          ],
        } as typeof emptyRunView);
      await vi.waitFor(() => expect(drawnSince(left)).toContain("■ Local"), {
        timeout: 3_000,
      });
    } finally {
      instance.unmount();
      rmSync(sessions, { recursive: true });
    }
  });

  it.each([
    ["Ctrl+K", "\x0b"],
    ["/search", "/search\r"],
  ])("searches tasks from %s and opens the picked one", async (_, opener) => {
    saveLayout(initialLayout());
    const found = {
      ...task(),
      id: "t9",
      title: "Fix the flaky test",
      last_activity_at: new Date(Date.now() - 2 * 3_600_000).toISOString(),
    };
    const search = vi.fn(async () => [found]);
    const mouse: MouseEvents = new EventEmitter();
    const { instance, output, type } = renderInTerminal(
      <App
        session={{
          work: {
            listRecent: async () => ({ tasks: [], hasMore: false }),
            get: async () => found,
            search,
          } as unknown as WorkList,
          runs: {
            watch: () => ({ stop: () => {}, loadOlder: async () => {} }),
            prefetch: async () => {},
          } as unknown as CloudRuns,
          chats: {} as PiChats,
          control: () => ({}) as PiControl,
          startLocal: () => Promise.reject(new Error("no local")),
        }}
        login={async () => {}}
        logout={() => {}}
        mouse={mouse}
      />,
    );
    // The terminal's bytes reach both Ink and the raw key stream.
    const press = (bytes: string): void => {
      mouse.emit("keys", bytes);
      type(bytes);
    };
    const drawnSince = (mark: number): string =>
      stripTerminalSequences(output().slice(mark));
    try {
      await vi.waitFor(() => expect(output()).toContain("No work yet"));
      press(opener);
      await vi.waitFor(() => expect(output()).toContain("Search tasks"));
      press("flaky");
      await vi.waitFor(() =>
        expect(drawnSince(0)).toMatch(/● Fix the flaky test\s+2h ago/),
      );
      expect(search).toHaveBeenLastCalledWith("flaky");

      const picked = output().length;
      press("\r");
      await vi.waitFor(() =>
        expect(drawnSince(picked)).toContain("^N new · ^\\ split"),
      );
      expect(drawnSince(picked)).toContain("Fix the flaky test");
    } finally {
      instance.unmount();
    }
  });

  it.each([
    ["the pane under the pointer", 0, "right"],
    ["the focused pane when the pointer report is stale", 1_000, "left"],
  ])("drops a file into %s", async (_, reportAge, expected) => {
    const split = splitFocused(initialLayout(), "row");
    const [left, right] = paneIds(activeWorkspace(split).root);
    saveLayout(focusPane(split, left));
    const mouse: MouseEvents = new EventEmitter();
    const { instance, output } = renderInTerminal(
      <App
        session={null}
        login={async () => {}}
        logout={() => {}}
        mouse={mouse}
      />,
    );
    try {
      await vi.waitFor(() => expect(output()).toContain("Type a message"));
      const now = Date.now();
      const clock = vi.spyOn(Date, "now").mockReturnValue(now);
      // Ghostty reports the pointer just before it pastes the dropped path.
      mouse.emit("move", { column: 90, row: 5 });
      clock.mockReturnValue(now + reportAge);
      mouse.emit("keys", "\x1b[200~/tmp/dropped.png\x1b[201~");
      clock.mockRestore();
      await vi.waitFor(() =>
        expect(activeWorkspace(loadLayout()).focusedPaneId).toBe(
          expected === "right" ? right : left,
        ),
      );
    } finally {
      instance.unmount();
    }
  });

  it("renames the chat at once, keeps it, and puts the old name back when a rename fails", async () => {
    const split = openTask(
      splitFocused(openTask(initialLayout(), "t1", "Old name"), "row"),
      "t2",
      "Other",
    );
    saveLayout(focusPane(split, paneIds(activeWorkspace(split).root)[0]));
    let answer = (): void => {};
    const rename = vi.fn(
      (taskId: string, title: string) =>
        new Promise<Task>((resolve, reject) => {
          answer = () =>
            title === "Bad name"
              ? reject(new Error("forbidden"))
              : resolve({ id: taskId, title, runtime: "pi" } as Task);
        }),
    );
    const mouse: MouseEvents = new EventEmitter();
    const { instance, output } = renderInTerminal(
      <App
        session={{
          work: {
            listRecent: () => new Promise(() => {}),
          } as unknown as WorkList,
          runs: { prefetch: async () => {} } as unknown as CloudRuns,
          chats: { rename } as unknown as PiChats,
          control: () => ({}) as PiControl,
          startLocal: () => Promise.reject(new Error("no local")),
        }}
        login={async () => {}}
        logout={() => {}}
        mouse={mouse}
      />,
    );
    const type = (text: string): void => {
      mouse.emit("keys", text);
      mouse.emit("keys", "\r");
    };
    try {
      await vi.waitFor(() => expect(output()).toContain("Old name"));
      // With no notice, the row is kept blank, so a notice never moves the chat.
      await vi.waitFor(() => {
        const rows = stripTerminalSequences(output()).split("\n");
        const rule = rows.findLastIndex((row) => /│ ─+ │/.test(row));
        expect(rows[rule - 2]).toContain("Loading chat");
        expect(rows[rule - 1].split("│")[1].trim()).toBe("");
      });
      type("/rename-workspace Infra");
      await vi.waitFor(() =>
        expect(activeWorkspace(loadLayout()).name).toBe("Infra"),
      );
      // The sidebar names the workspace instead of numbering it.
      await vi.waitFor(() => expect(output()).toContain("Infra"));
      type("/rename");
      await vi.waitFor(() => expect(output()).toContain("/rename Old name"));
      mouse.emit("keys", "\u007f".repeat("Old name".length));
      type("New name");
      await vi.waitFor(() =>
        expect(rename).toHaveBeenCalledWith("t1", "New name"),
      );
      // Shown before the server answers.
      await vi.waitFor(() => expect(output()).toContain("New name"));
      answer();
      await vi.waitFor(() =>
        expect(
          allPanes(loadLayout()).find((pane) => pane.taskId === "t1")?.title,
        ).toBe("New name"),
      );

      type("/rename Bad name");
      await vi.waitFor(() => expect(output()).toContain("Bad name"));
      answer();
      await vi.waitFor(() => expect(output()).toContain("Couldn't rename"));
      // The notice wraps in a row above the chat's composer, not under the sidebar.
      await vi.waitFor(() => {
        const rows = stripTerminalSequences(output()).split("\n");
        const end = rows.findLastIndex((row) => row.includes("forbidden"));
        expect(rows[end - 1]).toContain("Couldn't rename this chat: │");
        expect(rows[end]).toContain("forbidden │");
        expect(rows[end + 1]).toMatch(/│ ─+ │/);
        expect(rows[end + 2]).toContain("^N new");
      });
      // The latest frames draw the old name again.
      await vi.waitFor(() =>
        expect(output().lastIndexOf("New name")).toBeGreaterThan(
          output().lastIndexOf("Bad name"),
        ),
      );
    } finally {
      instance.unmount();
    }
  });

  it("narrows the sidebar with Ctrl+B and keeps it narrow, without losing other preferences", async () => {
    saveLayout(initialLayout());
    const mouse: MouseEvents = new EventEmitter();
    const { instance, output, type } = renderInTerminal(
      <App
        session={null}
        login={async () => {}}
        logout={() => {}}
        mouse={mouse}
      />,
    );
    try {
      await vi.waitFor(() => expect(output()).toContain("^N new"));
      mouse.emit("keys", "/local");
      mouse.emit("keys", "\r");
      await vi.waitFor(() => expect(loadPrefs().newChatPlace).toBe("local"));
      // App keys reach Ink through the terminal, as MouseInput forwards them.
      mouse.emit("keys", "\x02");
      type("\x02");
      await vi.waitFor(() => expect(loadPrefs().narrowSidebar).toBe(true));
      expect(loadPrefs().newChatPlace).toBe("local");
      // All tasks shrinks to its glyph, which the wide sidebar never draws.
      await vi.waitFor(() =>
        expect(stripTerminalSequences(output())).toContain(" ≡ "),
      );
    } finally {
      instance.unmount();
      rmSync(join(homedir(), ".config", "posthog-tui", "prefs.json"), {
        force: true,
      });
    }
  });

  it.each([
    ["finishes", null, null],
    // pi's request gives up after 30 seconds, while the compaction carries on.
    [
      "outlasts its request",
      "Timeout waiting for response to compact. Stderr: ",
      null,
    ],
    ["fails", "No model available", "Couldn't compact: No model available"],
  ])(
    "compacts a live local chat with /compact, and says so only when it fails, when it %s",
    async (outcome, failure, shown) => {
      const taskId = `compacting-${outcome.replaceAll(" ", "-")}`;
      const sessions = join(homedir(), ".config", "posthog-tui", "local");
      mkdirSync(sessions, { recursive: true });
      writeFileSync(join(sessions, `${taskId}.jsonl`), "");
      saveLayout(openTask(initialLayout(), taskId));
      const compact = vi.fn(async () => {
        if (failure) throw new Error(failure);
        return { tokensBefore: 150_000, estimatedTokensAfter: 32_000 };
      });
      const local = {
        watch: (onView: (view: typeof emptyRunView) => void) => {
          onView({ ...emptyRunView, loaded: true, status: "in_progress" });
          return () => {};
        },
        watchPrompts: () => () => {},
        stop: async () => {},
        control: {
          models: async () => ({ available: [], current: null }),
          efforts: async () => ({ available: [], current: null }),
          commands: async () => [],
          compact,
        },
      } as unknown as LocalSession;
      const mouse: MouseEvents = new EventEmitter();
      const { instance, output } = renderInTerminal(
        <App
          session={{
            work: {
              listRecent: async () => ({
                tasks: [{ id: taskId, title: "Local", runtime: "pi" } as Task],
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
        />,
      );
      try {
        await vi.waitFor(() => expect(output()).toContain("Local"));
        mouse.emit("keys", "/compact keep the test plan");
        mouse.emit("keys", "\r");
        await vi.waitFor(() =>
          expect(compact).toHaveBeenCalledWith("keep the test plan"),
        );
        if (shown) await vi.waitFor(() => expect(output()).toContain(shown));
        else {
          await new Promise((resolve) => setTimeout(resolve, 50));
          expect(output()).not.toContain("Couldn't compact");
        }
      } finally {
        instance.unmount();
        rmSync(sessions, { recursive: true });
      }
    },
  );

  it.each([
    ["after it was sent puts it back in the composer", 5_000, true],
    ["from before it was sent leaves it waiting", -60_000, false],
  ])(
    "takes a cloud message the backend could not deliver: a failure %s",
    async (_, failedAfterMs, putBack) => {
      saveLayout(openTask(initialLayout(), "cloud-chat"));
      const cloudTask = {
        id: "cloud-chat",
        title: "Cloud chat",
        runtime: "pi",
        latest_run: {
          id: "r1",
          status: "in_progress",
          environment: "cloud",
          state: {},
        },
      } as unknown as Task;
      // The pane and the sidebar's turn tracking both watch the run.
      const watchers: ((view: typeof emptyRunView) => void)[] = [];
      const showView = (view: typeof emptyRunView): void => {
        for (const watcher of watchers) watcher(view);
      };
      const entries = [
        { type: "pi_run_started", timestamp: new Date().toISOString() },
        {
          type: "pi_event",
          timestamp: new Date().toISOString(),
          event: {
            type: "user_message",
            id: "u1",
            timestamp: Date.now(),
            content: [{ type: "text", text: "First question" }],
          },
        },
        {
          type: "pi_event",
          timestamp: new Date().toISOString(),
          event: {
            type: "assistant_message_chunk",
            timestamp: Date.now(),
            content: { type: "text", text: "Earlier answer" },
          },
        },
        {
          type: "pi_event",
          timestamp: new Date().toISOString(),
          event: {
            type: "turn_completed",
            timestamp: Date.now(),
            stopReason: "stop",
          },
        },
      ];
      const viewWith = (more: unknown[] = []) => ({
        ...emptyRunView,
        loaded: true,
        status: "in_progress" as const,
        entries: [...entries, ...more] as typeof emptyRunView.entries,
      });
      const reply = vi.fn(async () => cloudTask);
      const mouse: MouseEvents = new EventEmitter();
      const { instance, output } = renderInTerminal(
        <App
          session={{
            work: {
              listRecent: async () => ({ tasks: [cloudTask], hasMore: false }),
            } as unknown as WorkList,
            runs: {
              prefetch: async () => {},
              watch: (
                _taskId: string,
                _runId: string,
                onView: (view: typeof emptyRunView) => void,
              ) => {
                watchers.push(onView);
                onView(viewWith());
                return { stop: () => {}, loadOlder: async () => {} };
              },
            } as unknown as CloudRuns,
            chats: { reply } as unknown as PiChats,
            control: () =>
              ({
                commands: async () => [],
                models: async () => ({ available: [], current: null }),
                efforts: async () => ({ available: [], current: null }),
              }) as unknown as PiControl,
            startLocal: () => Promise.reject(new Error("no local")),
          }}
          login={async () => {}}
          logout={() => {}}
          mouse={mouse}
        />,
      );
      try {
        await vi.waitFor(() => expect(watchers.length).toBeGreaterThan(0));
        mouse.emit("keys", "are you there");
        mouse.emit("keys", "\r");
        await vi.waitFor(() => expect(reply).toHaveBeenCalled());
        const sent = output().length;
        showView(
          viewWith([
            {
              type: "notification",
              timestamp: new Date(Date.now() + failedAfterMs).toISOString(),
              notification: {
                method: "_posthog/progress",
                params: {
                  step: "followup_delivery",
                  status: "failed",
                  label: "Couldn't deliver your message",
                  group: "followup-delivery:x:r1",
                  detail:
                    "RuntimeError: send_followup failed: Could not rebind credentials",
                },
              },
            },
          ]),
        );
        const drawn = (): string =>
          stripTerminalSequences(output().slice(sent));
        if (putBack) {
          await vi.waitFor(() =>
            expect(drawn()).toContain(
              "Couldn't deliver your message: Could not rebind credentials",
            ),
          );
          expect(drawn()).toContain("Your message is back in the composer");
        } else {
          await new Promise((resolve) => setTimeout(resolve, 200));
          expect(drawn()).not.toContain("back in the composer");
        }
      } finally {
        instance.unmount();
      }
    },
  );

  it("starts new chats where the last /local or /cloud pointed, after a restart", async () => {
    saveLayout(initialLayout());
    const session = {
      work: {
        listRecent: () => new Promise(() => {}),
      } as unknown as WorkList,
      runs: { prefetch: async () => {} } as unknown as CloudRuns,
      chats: {} as PiChats,
      control: () => ({}) as PiControl,
      startLocal: () => Promise.reject(new Error("no local")),
    };
    const mouse: MouseEvents = new EventEmitter();
    const app = (): ReturnType<typeof renderInTerminal> =>
      renderInTerminal(
        <App
          session={session}
          login={async () => {}}
          logout={() => {}}
          mouse={mouse}
        />,
      );

    const first = app();
    try {
      await vi.waitFor(() =>
        expect(first.output()).toContain("start a cloud run"),
      );
      mouse.emit("keys", "/local");
      mouse.emit("keys", "\r");
      await vi.waitFor(() =>
        expect(first.output()).toContain("start a local chat"),
      );
    } finally {
      first.instance.unmount();
    }

    const second = app();
    try {
      await vi.waitFor(() =>
        expect(second.output()).toContain("start a local chat"),
      );
    } finally {
      second.instance.unmount();
      rmSync(join(homedir(), ".config", "posthog-tui", "prefs.json"), {
        force: true,
      });
    }
  });

  // A signed-in app on local chat t5, in a full-height frame as Root gives it, so the chat has rows to draw messages in.
  const localApp = () => {
    initTheme("dark");
    const sessions = join(homedir(), ".config", "posthog-tui", "local");
    mkdirSync(sessions, { recursive: true });
    writeFileSync(join(sessions, "t5.jsonl"), "");
    saveLayout(openTask(initialLayout(), "t5"), layoutPath("user-1"));
    const agent = () =>
      ({
        watch: (onView: (view: typeof emptyRunView) => void) => {
          onView({ ...emptyRunView, loaded: true, status: "in_progress" });
          return () => {};
        },
        watchPrompts: () => () => {},
        prompt: async () => {},
        stop: vi.fn(async () => {}),
        control: {
          models: async () => ({ available: [], current: null }),
          efforts: async () => ({ available: [], current: null }),
          commands: async () => [],
        },
      }) as unknown as LocalSession;
    const first = agent();
    const mouse: MouseEvents = new EventEmitter();
    const app = (local: LocalSession | null) => (
      <Box height={30} flexDirection="column">
        <App
          session={
            local && {
              account: "user-1",
              work: {
                listRecent: async () => ({
                  tasks: [{ id: "t5", title: "Local", runtime: "pi" } as Task],
                  hasMore: false,
                }),
              } as unknown as WorkList,
              runs: { prefetch: async () => {} } as unknown as CloudRuns,
              chats: {} as PiChats,
              control: () => ({}) as PiControl,
              startLocal: async () => local,
            }
          }
          login={async () => {}}
          logout={() => instance.rerender(app(null))}
          mouse={mouse}
        />
      </Box>
    );
    const { instance, output, type } = renderInTerminal(app(first));
    return {
      output,
      first,
      signIn: () => instance.rerender(app(agent())),
      press: (bytes: string): void => {
        mouse.emit("keys", bytes);
        type(bytes);
      },
      drawnSince: (mark: number): string =>
        stripTerminalSequences(output().slice(mark)),
      close: (): void => {
        instance.unmount();
        rmSync(sessions, { recursive: true });
      },
    };
  };

  it("keeps the account's layout through a sign-out", async () => {
    const { output, press, drawnSince, close } = localApp();
    try {
      await vi.waitFor(() => expect(drawnSince(0)).toContain("Local ·"));
      // Ctrl+\\ splits, so the saved layout differs from a fresh one.
      press("\x1c");
      const saved = (): number =>
        allPanes(loadLayout(layoutPath("user-1"))).length;
      await vi.waitFor(() => expect(saved()).toBe(2));
      press("/logout");
      press("\r");
      await vi.waitFor(() => expect(output()).toContain("Signed out"));
      expect(saved()).toBe(2);
    } finally {
      close();
    }
  });

  it("stops running local agents on a new sign-in", async () => {
    const { first, signIn, drawnSince, close } = localApp();
    try {
      await vi.waitFor(() => expect(drawnSince(0)).toContain("Local ·"));
      signIn();
      await vi.waitFor(() => expect(first.stop).toHaveBeenCalled());
    } finally {
      close();
    }
  });

  it("keeps a sent message out of the next chat the pane shows", async () => {
    const { output, press, drawnSince, close } = localApp();
    try {
      await vi.waitFor(() => expect(drawnSince(0)).toContain("Local ·"));
      press("hello?");
      press("\r");
      await vi.waitFor(() => expect(drawnSince(0)).toContain("hello?"));
      const sent = output().length;
      // Ctrl+N puts a new chat in the same pane.
      press("\x0e");
      await vi.waitFor(() => expect(drawnSince(sent)).toContain("New chat"));
      expect(drawnSince(sent)).not.toContain("hello?");
    } finally {
      close();
    }
  });

  it("keeps a sent message out of the next chat the pane shows", async () => {
    const { output, press, drawnSince, close } = localApp();
    try {
      await vi.waitFor(() => expect(drawnSince(0)).toContain("Local ·"));
      press("hello?");
      press("\r");
      await vi.waitFor(() => expect(drawnSince(0)).toContain("hello?"));
      const sent = output().length;
      // Ctrl+N puts a new chat in the same pane.
      press("\x0e");
      await vi.waitFor(() => expect(drawnSince(sent)).toContain("New chat"));
      expect(drawnSince(sent)).not.toContain("hello?");
    } finally {
      close();
    }
  });
});
