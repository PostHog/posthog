import type { Task } from "@posthog/shared";
import { renderToString } from "ink";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PiChats } from "../chats";
import { initialLayout, openTask, saveLayout } from "../layout";
import type { PiControl } from "../models";
import type { CloudRuns } from "../runs";
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
          work={work}
          runs={{} as CloudRuns}
          chats={{} as PiChats}
          control={() => ({}) as PiControl}
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
        work={work}
        runs={runs}
        chats={{} as PiChats}
        control={() => ({}) as PiControl}
      />,
    );
    await vi.waitFor(() => expect(runs.watch).toHaveBeenCalledTimes(1));
    for (let refresh = 0; refresh < 3; refresh++) {
      await vi.advanceTimersByTimeAsync(10_000);
    }
    instance.unmount();

    expect(runs.watch).toHaveBeenCalledTimes(1);
  });
});
