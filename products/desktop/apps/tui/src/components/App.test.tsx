import { EventEmitter } from "node:events";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import type { Task } from "@posthog/shared";
import { renderToString } from "ink";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PiChats } from "../chats";
import { initialLayout, openTask, saveLayout } from "../layout";
import type { LocalSession } from "../local";
import { type PiControl, STARTING_MODEL } from "../models";
import type { MouseEvents } from "../mouse";
import { type CloudRuns, emptyRunView } from "../runs";
import { renderInTerminal } from "../testing";
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
});
